#!/usr/bin/env python3
"""mobil-xml · core/orchestrator.py

Orquestador asíncrono:
  * Consume tareas JSON desde una cola Redis con semántica "at-least-once":
    BLMOVE a una lista de procesamiento propia (``<prefix><INSTANCE_ID>``);
    una tarea solo sale de ahí cuando su resultado (ok / reintento / dead-letter)
    queda registrado de forma atómica. Al arrancar se recuperan las tareas que
    quedaron en esa lista por una caída. Asume UNA instancia por INSTANCE_ID.
  * Usa la API local de Ollama para generar texto con acento regional / nicho.
  * Ejecuta comandos ADB sobre uno o varios dispositivos, serializando el acceso
    por dispositivo y reconectando solo si el dispositivo es de red (host:puerto).
  * Los reintentos CONTINÚAN desde la primera acción no completada (no repiten
    acciones ya ejecutadas).

Formato de tarea (JSON en la lista Redis ``REDIS_QUEUE``)::

    {
      "id": "tarea-001",
      "device": "redroid-1:5555",
      "locale": "es-DO",
      "niche": "tecnología",
      "actions": [
        {"type": "open_app", "package": "com.example.app"},
        {"type": "wait", "min": 1.5, "max": 3.0},
        {"type": "tap", "x": 540, "y": 1600},
        {"type": "generate", "prompt": "Comenta sobre el nuevo teléfono", "max_chars": 140},
        {"type": "type_text", "use_generated": true},
        {"type": "key", "key": "KEYCODE_ENTER"}
      ]
    }

Acciones: tap, swipe, key, open_app, wait, setup_ime, generate, type_text.

Resultados: ``mobil:result:<id>`` (TTL configurable). Tareas fallidas se
reintentan; agotados los intentos van a ``REDIS_DEAD_QUEUE``.

Límites conocidos: si se agota el tiempo o el proceso muere a mitad de una acción
(p. ej. ``type_text``), esa acción se repite completa al reintentar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import shlex
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import redis.asyncio as aioredis
from redis.exceptions import RedisError

log = logging.getLogger("mobil.core")

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, "").split(",") if x.strip())


@dataclass(frozen=True)
class Config:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue: str = os.getenv("REDIS_QUEUE", "mobil:tasks")
    dead_queue: str = os.getenv("REDIS_DEAD_QUEUE", "mobil:tasks:dead")
    processing_prefix: str = os.getenv("REDIS_PROCESSING_PREFIX", "mobil:tasks:processing:")
    result_prefix: str = os.getenv("REDIS_RESULT_PREFIX", "mobil:result:")
    result_ttl: int = _env_int("RESULT_TTL_SECONDS", 86400)
    poll_timeout: int = _env_int("REDIS_POLL_TIMEOUT", 5)
    instance_id: str = os.getenv("INSTANCE_ID", "orchestrator-1")

    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_timeout: float = _env_float("OLLAMA_TIMEOUT", 120.0)
    ollama_retries: int = _env_int("OLLAMA_RETRIES", 2)

    adb_path: str = os.getenv("ADB_PATH", "adb")
    adb_timeout: float = _env_float("ADB_TIMEOUT", 20.0)
    ime_id: str = os.getenv("ADB_IME_ID", "com.android.adbkeyboard/.AdbIME")
    # Dispositivos de red a los que conectarse al arrancar (host:puerto, separados por coma)
    adb_targets: tuple[str, ...] = _env_csv("ADB_TARGETS")
    # Lista blanca de seriales aceptados en tareas (vacío = cualquiera que pase la validación)
    allowed_devices: tuple[str, ...] = _env_csv("ALLOWED_DEVICES")

    workers: int = _env_int("WORKERS", 4)
    max_attempts: int = _env_int("MAX_ATTEMPTS", 3)
    retry_backoff: float = _env_float("RETRY_BACKOFF", 5.0)
    task_timeout: float = _env_float("TASK_TIMEOUT", 300.0)
    shutdown_grace: float = _env_float("SHUTDOWN_GRACE", 30.0)

    min_delay: float = _env_float("HUMAN_MIN_DELAY", 0.4)
    max_delay: float = _env_float("HUMAN_MAX_DELAY", 1.8)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    heartbeat_path: str = os.getenv("HEARTBEAT_PATH", "/tmp/orchestrator.alive")
    heartbeat_interval: float = _env_float("HEARTBEAT_INTERVAL", 10.0)

    @property
    def processing_queue(self) -> str:
        return f"{self.processing_prefix}{self.instance_id}"


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_KEY_RE = re.compile(r"^(KEYCODE_[A-Z0-9_]+|\d{1,3})$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8}){0,2}$")
_NICHE_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
_DISCONNECTED_RE = re.compile(r"not found|offline|no devices|cannot connect|device .* not|closed", re.I)

MAX_TASK_BYTES = 64 * 1024
MAX_ACTIONS = 200
MAX_TEXT = 2000
MAX_COORD = 10_000
MAX_WAIT_SECONDS = 60.0
MAX_PRESS_MS = 10_000


class TaskError(Exception):
    """Tarea inválida: no se reintenta."""


class AdbError(Exception):
    """Fallo al ejecutar ADB: se reintenta."""


class OllamaError(Exception):
    """Fallo al hablar con Ollama: se reintenta."""


def _num(
    obj: dict[str, Any],
    key: str,
    *,
    lo: float,
    hi: float,
    kind: type = int,
    default: Any = None,
    required: bool = True,
) -> Any:
    """Lee y valida un número acotado. Cualquier problema -> TaskError (nunca ValueError)."""
    if key not in obj or obj[key] is None:
        if required:
            raise TaskError(f"Parámetro requerido: {key!r}")
        return default
    raw = obj[key]
    if isinstance(raw, bool):
        raise TaskError(f"Parámetro {key!r} no puede ser booleano")
    try:
        val = kind(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TaskError(f"Parámetro numérico inválido: {key!r}") from exc
    if kind is float and not math.isfinite(val):
        raise TaskError(f"Parámetro {key!r} no es finito")
    if not (lo <= val <= hi):
        raise TaskError(f"Parámetro {key!r} fuera de rango [{lo}, {hi}]")
    return val


def _validate_action(i: int, act: dict[str, Any]) -> None:
    """Valida y normaliza una acción in-place. Lanza TaskError si es inválida."""
    kind = act.get("type")
    if not isinstance(kind, str):
        raise TaskError(f"Acción #{i}: 'type' debe ser texto")

    if kind == "tap":
        act["x"] = _num(act, "x", lo=0, hi=MAX_COORD)
        act["y"] = _num(act, "y", lo=0, hi=MAX_COORD)
        act["long_press_ms"] = _num(act, "long_press_ms", lo=0, hi=MAX_PRESS_MS, required=False, default=0)
    elif kind == "swipe":
        for k in ("x1", "y1", "x2", "y2"):
            act[k] = _num(act, k, lo=0, hi=MAX_COORD)
        act["duration_ms"] = _num(act, "duration_ms", lo=0, hi=MAX_PRESS_MS, required=False, default=0)
    elif kind == "key":
        if not _KEY_RE.match(str(act.get("key", ""))):
            raise TaskError(f"Acción #{i}: keycode inválido")
    elif kind == "open_app":
        if not _PACKAGE_RE.match(str(act.get("package", ""))):
            raise TaskError(f"Acción #{i}: paquete inválido")
    elif kind == "wait":
        lo = _num(act, "min", lo=0.0, hi=MAX_WAIT_SECONDS, kind=float, required=False, default=1.0)
        hi = _num(act, "max", lo=0.0, hi=MAX_WAIT_SECONDS, kind=float, required=False, default=max(lo, 3.0))
        if hi < lo:
            raise TaskError(f"Acción #{i}: 'max' debe ser >= 'min'")
        act["min"], act["max"] = lo, hi
    elif kind == "setup_ime":
        pass
    elif kind == "generate":
        prompt = act.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise TaskError(f"Acción #{i}: 'generate' requiere 'prompt'")
        if len(prompt) > MAX_TEXT:
            raise TaskError(f"Acción #{i}: 'prompt' demasiado largo")
        if "locale" in act and not _LOCALE_RE.match(str(act["locale"])):
            raise TaskError(f"Acción #{i}: locale inválido")
        if "niche" in act and not _NICHE_RE.match(str(act["niche"])):
            raise TaskError(f"Acción #{i}: niche inválido")
        act["max_chars"] = _num(act, "max_chars", lo=1, hi=MAX_TEXT, required=False, default=200)
    elif kind == "type_text":
        if act.get("use_generated"):
            return
        text = act.get("text")
        if not isinstance(text, str) or not text:
            raise TaskError(f"Acción #{i}: 'type_text' requiere 'text' o 'use_generated'")
        if len(text) > MAX_TEXT:
            raise TaskError(f"Acción #{i}: 'text' demasiado largo")
    else:
        raise TaskError(f"Acción #{i}: tipo desconocido {kind!r}")


@dataclass
class Task:
    id: str
    device: str
    actions: list[dict[str, Any]]
    locale: str = "es-DO"
    niche: str = "general"
    attempts: int = 0
    resume_at: int = 0  # índice de la primera acción pendiente (para reintentos)
    generated: str = ""  # texto generado acumulado (para reintentos)

    @classmethod
    def parse(cls, raw: str, allowed_devices: tuple[str, ...] = ()) -> "Task":
        if len(raw) > MAX_TASK_BYTES:
            raise TaskError("Tarea demasiado grande")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise TaskError(f"JSON inválido: {exc}") from exc
        if not isinstance(data, dict):
            raise TaskError("La tarea debe ser un objeto JSON")

        device = str(data.get("device", ""))
        if not _SERIAL_RE.match(device):
            raise TaskError(f"Serial de dispositivo inválido: {device!r}")
        if allowed_devices and device not in allowed_devices:
            raise TaskError(f"Dispositivo no permitido: {device!r}")

        task_id = str(data.get("id") or uuid.uuid4())
        if not _TASK_ID_RE.match(task_id):
            raise TaskError("Id de tarea inválido")

        locale = str(data.get("locale", "es-DO"))
        if not _LOCALE_RE.match(locale):
            raise TaskError(f"locale inválido: {locale!r}")
        niche = str(data.get("niche", "general"))
        if not _NICHE_RE.match(niche):
            raise TaskError("niche inválido")

        actions = data.get("actions")
        if not isinstance(actions, list) or not actions:
            raise TaskError("'actions' debe ser una lista no vacía")
        if len(actions) > MAX_ACTIONS:
            raise TaskError(f"Demasiadas acciones (máx. {MAX_ACTIONS})")
        for i, act in enumerate(actions):
            if not isinstance(act, dict) or "type" not in act:
                raise TaskError(f"Acción #{i} inválida")
            _validate_action(i, act)

        attempts = _num(data, "attempts", lo=0, hi=1000, required=False, default=0)
        resume_at = _num(data, "resume_at", lo=0, hi=len(actions), required=False, default=0)
        generated = data.get("generated", "")
        if not isinstance(generated, str) or len(generated) > MAX_TEXT:
            raise TaskError("'generated' inválido")

        return cls(
            id=task_id,
            device=device,
            actions=actions,
            locale=locale,
            niche=niche,
            attempts=attempts,
            resume_at=resume_at,
            generated=generated,
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "device": self.device,
                "actions": self.actions,
                "locale": self.locale,
                "niche": self.niche,
                "attempts": self.attempts,
                "resume_at": self.resume_at,
                "generated": self.generated,
            },
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Humanización
# ---------------------------------------------------------------------------


class Humanizer:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def jitter(self, value: int, sigma: float = 4.0) -> int:
        return max(0, int(round(random.gauss(value, sigma))))

    async def pause(self, lo: float | None = None, hi: float | None = None) -> None:
        lo = self.cfg.min_delay if lo is None else lo
        hi = self.cfg.max_delay if hi is None else hi
        delay = random.uniform(lo, hi)
        if random.random() < 0.07:  # micro-distracción ocasional
            delay += random.uniform(0.8, 2.5)
        await asyncio.sleep(delay)

    @staticmethod
    def chunks(text: str) -> list[str]:
        out, i = [], 0
        while i < len(text):
            n = random.randint(1, 5)
            out.append(text[i : i + n])
            i += n
        return out

    @staticmethod
    def typing_delay(chunk: str) -> float:
        delay = random.uniform(0.05, 0.25)
        if chunk.endswith((" ", ",", ".", "!", "?")):
            delay += random.uniform(0.1, 0.45)
        if random.random() < 0.03:
            delay += random.uniform(0.6, 1.5)
        return delay


# ---------------------------------------------------------------------------
# ADB
# ---------------------------------------------------------------------------


class Adb:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process | None) -> None:
        """Mata y recolecta el subproceso para no dejar huérfanos/zombis."""
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:  # noqa: BLE001
            pass

    async def _exec(self, *cmd: str) -> str:
        log.debug("ADB: %s", " ".join(cmd))
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.cfg.adb_timeout)
        except asyncio.TimeoutError as exc:
            await self._reap(proc)
            raise AdbError(f"Timeout ADB: {' '.join(cmd[1:])}") from exc
        except asyncio.CancelledError:
            await self._reap(proc)
            raise
        except FileNotFoundError as exc:
            raise AdbError(f"No se encontró el binario ADB: {self.cfg.adb_path}") from exc
        except OSError as exc:
            raise AdbError(f"No se pudo ejecutar ADB: {exc}") from exc

        if proc.returncode != 0:
            raise AdbError(
                f"ADB falló ({proc.returncode}): {err.decode(errors='replace').strip()}"
            )
        return out.decode(errors="replace").strip()

    async def run(self, serial: str, *args: str) -> str:
        return await self._exec(self.cfg.adb_path, "-s", serial, *args)

    async def connect(self, target: str) -> None:
        """`adb connect host:puerto`. adb devuelve 0 aunque falle, así que se valida la salida."""
        if not _SERIAL_RE.match(target):
            raise AdbError(f"Destino ADB inválido: {target!r}")
        out = await self._exec(self.cfg.adb_path, "connect", target)
        if "connected to" not in out.lower():
            raise AdbError(f"No se pudo conectar a {target}: {out}")

    async def shell(self, serial: str, command: str) -> str:
        try:
            return await self.run(serial, "shell", command)
        except AdbError as exc:
            # Solo dispositivos de red (host:puerto) se pueden reconectar.
            if ":" in serial and _DISCONNECTED_RE.search(str(exc)):
                log.warning("Dispositivo %s desconectado; reconectando…", serial)
                await self.connect(serial)
                return await self.run(serial, "shell", command)
            raise


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

DIALECTS: dict[str, str] = {
    "es-DO": "español dominicano coloquial (expresiones como 'tato', 'vaina', 'qué lo qué', sin exagerar)",
    "es-MX": "español mexicano coloquial (expresiones como 'padre', 'qué onda', sin exagerar)",
    "es-AR": "español rioplatense (voseo, expresiones como 'che', 'bárbaro', sin exagerar)",
    "es-CO": "español colombiano coloquial (expresiones como 'parce', 'chévere', sin exagerar)",
    "es-ES": "español de España coloquial (expresiones como 'vale', 'guay', sin exagerar)",
    "es-PR": "español puertorriqueño coloquial",
    "en-US": "American English, casual and natural",
    "en-GB": "British English, casual and natural",
    "pt-BR": "português brasileiro coloquial",
}


class OllamaClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.ollama_url, timeout=cfg.ollama_timeout
        )

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _system_prompt(locale: str, niche: str, max_chars: int) -> str:
        dialect = DIALECTS.get(locale, f"el idioma/variante regional '{locale}', con expresiones naturales")
        return (
            f"Eres un redactor nativo. Escribe en {dialect}. "
            f"Nicho/tema de contexto: {niche}. "
            f"Responde SOLO con el texto final, máximo {max_chars} caracteres, "
            "sin comillas, sin explicaciones, sin hashtags salvo que se pidan."
        )

    async def generate(
        self, prompt: str, locale: str, niche: str, max_chars: int = 200
    ) -> str:
        payload = {
            "model": self.cfg.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": self._system_prompt(locale, niche, max_chars)},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.8, "top_p": 0.9},
        }
        last: Exception | None = None
        for attempt in range(self.cfg.ollama_retries + 1):
            try:
                resp = await self._http.post("/api/chat", json=payload)
                resp.raise_for_status()
                text = resp.json()["message"]["content"].strip().strip('"“”').strip()
                if not text:
                    raise OllamaError("Respuesta vacía de Ollama")
                return text[:max_chars].rstrip()
            except (httpx.HTTPError, KeyError, TypeError, ValueError, OllamaError) as exc:
                last = exc
                log.warning("Ollama intento %d falló: %s", attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        raise OllamaError(f"Ollama no disponible: {last}")


# ---------------------------------------------------------------------------
# Ejecución de acciones sobre un dispositivo
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    task: Task
    generated: str = ""
    completed: int = 0  # acciones completadas (incluye las de intentos previos)
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.generated:
            self.generated = self.task.generated
        self.completed = max(self.completed, self.task.resume_at)


class DeviceExecutor:
    def __init__(self, cfg: Config, adb: Adb, ollama: OllamaClient, human: Humanizer) -> None:
        self.cfg, self.adb, self.ollama, self.human = cfg, adb, ollama, human
        self._handlers: dict[str, Callable[[RunContext, dict], Awaitable[None]]] = {
            "tap": self._tap,
            "swipe": self._swipe,
            "key": self._key,
            "open_app": self._open_app,
            "wait": self._wait,
            "setup_ime": self._setup_ime,
            "generate": self._generate,
            "type_text": self._type_text,
        }

    async def execute(self, ctx: RunContext) -> None:
        actions = ctx.task.actions
        for i in range(ctx.task.resume_at, len(actions)):
            act = actions[i]
            kind = act["type"]
            handler = self._handlers.get(kind)
            if handler is None:
                raise TaskError(f"Acción desconocida: {kind!r}")
            log.info("[%s] %s #%d → %s", ctx.task.id, ctx.task.device, i, kind)
            await handler(ctx, act)
            ctx.completed = i + 1
            ctx.log.append(kind)
            if kind not in ("wait", "generate"):
                await self.human.pause()

    # -- acciones ----------------------------------------------------------

    @staticmethod
    def _int(act: dict, key: str) -> int:
        return _num(act, key, lo=0, hi=MAX_COORD)

    async def _tap(self, ctx: RunContext, act: dict) -> None:
        x = self.human.jitter(self._int(act, "x"))
        y = self.human.jitter(self._int(act, "y"))
        long_ms = _num(act, "long_press_ms", lo=0, hi=MAX_PRESS_MS, required=False, default=0)
        if long_ms > 0:
            await self.adb.shell(ctx.task.device, f"input swipe {x} {y} {x} {y} {long_ms}")
        else:
            hold = random.randint(40, 140)  # pulsación corta con duración natural
            await self.adb.shell(ctx.task.device, f"input swipe {x} {y} {x} {y} {hold}")

    async def _swipe(self, ctx: RunContext, act: dict) -> None:
        x1 = self.human.jitter(self._int(act, "x1"), 6)
        y1 = self.human.jitter(self._int(act, "y1"), 6)
        x2 = self.human.jitter(self._int(act, "x2"), 6)
        y2 = self.human.jitter(self._int(act, "y2"), 6)
        dur = _num(act, "duration_ms", lo=0, hi=MAX_PRESS_MS, required=False, default=0) or random.randint(250, 650)
        await self.adb.shell(ctx.task.device, f"input swipe {x1} {y1} {x2} {y2} {dur}")

    async def _key(self, ctx: RunContext, act: dict) -> None:
        key = str(act.get("key", ""))
        if not _KEY_RE.match(key):
            raise TaskError(f"Keycode inválido: {key!r}")
        await self.adb.shell(ctx.task.device, f"input keyevent {key}")

    async def _open_app(self, ctx: RunContext, act: dict) -> None:
        pkg = str(act.get("package", ""))
        if not _PACKAGE_RE.match(pkg):
            raise TaskError(f"Paquete inválido: {pkg!r}")
        await self.adb.shell(
            ctx.task.device,
            f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
        )
        await asyncio.sleep(random.uniform(1.5, 3.0))

    async def _wait(self, ctx: RunContext, act: dict) -> None:
        lo = _num(act, "min", lo=0.0, hi=MAX_WAIT_SECONDS, kind=float, required=False, default=1.0)
        hi = _num(act, "max", lo=0.0, hi=MAX_WAIT_SECONDS, kind=float, required=False, default=max(lo, 3.0))
        if hi < lo:
            raise TaskError("'max' debe ser >= 'min'")
        await asyncio.sleep(random.uniform(lo, hi))

    async def _setup_ime(self, ctx: RunContext, act: dict) -> None:
        """Activa ADBKeyboard (requerido para acentos/ñ/emoji)."""
        ime = self.cfg.ime_id
        await self.adb.shell(ctx.task.device, f"ime enable {shlex.quote(ime)}")
        await self.adb.shell(ctx.task.device, f"ime set {shlex.quote(ime)}")

    async def _generate(self, ctx: RunContext, act: dict) -> None:
        prompt = str(act.get("prompt", "")).strip()
        if not prompt:
            raise TaskError("'generate' requiere 'prompt'")
        ctx.generated = await self.ollama.generate(
            prompt=prompt,
            locale=str(act.get("locale", ctx.task.locale)),
            niche=str(act.get("niche", ctx.task.niche)),
            max_chars=_num(act, "max_chars", lo=1, hi=MAX_TEXT, required=False, default=200),
        )
        log.info("[%s] Texto generado (%d chars)", ctx.task.id, len(ctx.generated))

    @staticmethod
    def _needs_ime(chunk: str) -> bool:
        return any(ord(c) > 126 or ord(c) < 32 or c in "%\\" for c in chunk)

    async def _type_text(self, ctx: RunContext, act: dict) -> None:
        text = ctx.generated if act.get("use_generated") else str(act.get("text", ""))
        if not text:
            raise TaskError("'type_text' sin texto (usa 'text' o 'use_generated')")

        for chunk in self.human.chunks(text):
            if self._needs_ime(chunk):
                await self.adb.shell(
                    ctx.task.device,
                    f"am broadcast -a ADB_INPUT_TEXT --es msg {shlex.quote(chunk)}",
                )
            else:
                encoded = shlex.quote(chunk.replace(" ", "%s"))
                await self.adb.shell(ctx.task.device, f"input text {encoded}")
            await asyncio.sleep(self.human.typing_delay(chunk))


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------


class Orchestrator:
    def __init__(self, cfg: Config, redis: aioredis.Redis | None = None) -> None:
        self.cfg = cfg
        self.redis = redis or aioredis.from_url(
            cfg.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            health_check_interval=30,
        )
        self.adb = Adb(cfg)
        self.ollama = OllamaClient(cfg)
        self.executor = DeviceExecutor(cfg, self.adb, self.ollama, Humanizer(cfg))
        self._locks: dict[str, asyncio.Lock] = {}
        self._stop = asyncio.Event()

    # -- control -----------------------------------------------------------

    def stop(self) -> None:
        log.info("Señal de parada recibida; cerrando de forma ordenada…")
        self._stop.set()

    def _lock(self, device: str) -> asyncio.Lock:
        return self._locks.setdefault(device, asyncio.Lock())

    async def _sleep(self, seconds: float) -> None:
        """Duerme, pero se interrumpe si se pide parar."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # -- arranque ----------------------------------------------------------

    async def connect_devices(self) -> None:
        for target in self.cfg.adb_targets:
            try:
                await self.adb.connect(target)
                log.info("ADB conectado: %s", target)
            except AdbError as exc:
                # Redroid puede tardar en arrancar: se reconectará de forma perezosa en la primera tarea.
                log.warning("No se pudo conectar a %s todavía: %s", target, exc)

    async def recover_processing(self) -> int:
        """Devuelve a la cola (al frente) las tareas que quedaron a medias por una caída."""
        moved = 0
        while True:
            item = await self.redis.lmove(
                self.cfg.processing_queue, self.cfg.queue, src="RIGHT", dest="LEFT"
            )
            if item is None:
                break
            moved += 1
        if moved:
            log.warning("Recuperadas %d tarea(s) interrumpidas desde %s", moved, self.cfg.processing_queue)
        return moved

    async def run(self) -> None:
        await self.redis.ping()
        await self.connect_devices()
        await self.recover_processing()
        log.info(
            "Orquestador listo · cola=%s · workers=%d · modelo=%s",
            self.cfg.queue, self.cfg.workers, self.cfg.ollama_model,
        )
        workers = [asyncio.create_task(self._worker(n)) for n in range(self.cfg.workers)]
        heartbeat = asyncio.create_task(self._heartbeat())
        await self._stop.wait()
        _, pending = await asyncio.wait(workers, timeout=self.cfg.shutdown_grace)
        for t in [*pending, heartbeat]:
            t.cancel()
        await asyncio.gather(*pending, heartbeat, return_exceptions=True)
        await self.ollama.close()
        await self.redis.aclose()
        log.info("Orquestador detenido")

    async def _heartbeat(self) -> None:
        """Marca de vida para el healthcheck de Docker."""
        path = Path(self.cfg.heartbeat_path)
        while not self._stop.is_set():
            try:
                path.write_text(str(time.time()))
            except OSError as exc:
                log.warning("No se pudo escribir el heartbeat: %s", exc)
            await self._sleep(self.cfg.heartbeat_interval)

    # -- workers -----------------------------------------------------------

    async def _worker(self, n: int) -> None:
        """Supervisor: un worker NUNCA muere por una excepción inesperada."""
        while not self._stop.is_set():
            try:
                await self._worker_loop(n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Worker %d falló; reiniciando en 2s", n)
                await self._sleep(2.0)

    async def _worker_loop(self, n: int) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                raw = await self.redis.blmove(
                    self.cfg.queue,
                    self.cfg.processing_queue,
                    self.cfg.poll_timeout,
                    src="LEFT",
                    dest="RIGHT",
                )
                backoff = 1.0
            except RedisError as exc:
                log.error("Redis error (worker %d): %s", n, exc)
                await self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            if raw is None:
                await asyncio.sleep(0)  # cede el control si Redis respondió sin bloquear
                continue
            try:
                await self._handle(raw)
            except asyncio.CancelledError:
                raise  # la tarea sigue en la lista de procesamiento: se recupera al reiniciar
            except Exception:  # noqa: BLE001 - nunca tumbar el worker
                log.exception("Error no controlado manejando tarea (queda en procesamiento)")

    # -- manejo de tareas --------------------------------------------------

    async def _handle(self, raw: str) -> None:
        try:
            task = Task.parse(raw, self.cfg.allowed_devices)
        except TaskError as exc:
            log.error("Tarea descartada: %s", exc)
            await self._finish(raw, push_dead=self._dead_payload(raw, str(exc)))
            return

        ctx = RunContext(task=task)
        started = time.monotonic()
        try:
            async with self._lock(task.device):
                await asyncio.wait_for(self.executor.execute(ctx), timeout=self.cfg.task_timeout)
        except TaskError as exc:
            log.error("[%s] tarea inválida: %s", task.id, exc)
            await self._store(task, "invalid", {"error": str(exc)})
            await self._finish(raw, push_dead=self._dead_payload(raw, str(exc)))
        except (AdbError, OllamaError, asyncio.TimeoutError, RedisError) as exc:
            await self._retry(raw, task, ctx, exc)
        except Exception:  # noqa: BLE001 - nunca tumbar el worker
            log.exception("[%s] error inesperado", task.id)
            await self._retry(raw, task, ctx, RuntimeError("error inesperado"))
        else:
            elapsed = round(time.monotonic() - started, 2)
            await self._store(
                task, "ok", {"actions": ctx.log, "generated": ctx.generated, "elapsed": elapsed}
            )
            await self._finish(raw)
            log.info("[%s] completada en %.1fs", task.id, elapsed)

    async def _retry(self, raw: str, task: Task, ctx: RunContext, exc: Exception) -> None:
        task.attempts += 1
        task.resume_at = ctx.completed  # no repetir lo ya hecho
        task.generated = ctx.generated
        if task.attempts >= self.cfg.max_attempts:
            log.error("[%s] agotados los intentos: %s", task.id, exc)
            await self._store(task, "failed", {"error": str(exc), "attempts": task.attempts})
            await self._finish(raw, push_dead=self._dead_payload(task.to_json(), str(exc)))
            return
        delay = self.cfg.retry_backoff * (2 ** (task.attempts - 1))
        log.warning(
            "[%s] reintento %d/%d en %.0fs (desde acción #%d): %s",
            task.id, task.attempts, self.cfg.max_attempts, delay, task.resume_at, exc,
        )
        await self._sleep(delay)  # la tarea sigue protegida en la lista de procesamiento
        await self._finish(raw, push_queue=task.to_json())

    # -- Redis auxiliar ----------------------------------------------------

    @staticmethod
    def _dead_payload(task_json: str, reason: str) -> str:
        return json.dumps({"reason": reason, "task": task_json}, ensure_ascii=False)

    async def _finish(
        self, raw: str, *, push_queue: str | None = None, push_dead: str | None = None
    ) -> bool:
        """Saca la tarea de 'processing' y (opcional) la reencola o manda a dead-letter, ATÓMICAMENTE.

        Si Redis falla tras varios intentos la tarea queda en 'processing' y se recupera al reiniciar.
        """
        for attempt in range(3):
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    if push_queue is not None:
                        pipe.rpush(self.cfg.queue, push_queue)
                    if push_dead is not None:
                        pipe.rpush(self.cfg.dead_queue, push_dead)
                    pipe.lrem(self.cfg.processing_queue, 1, raw)
                    await pipe.execute()
                return True
            except RedisError as exc:
                log.error("No se pudo cerrar la tarea (intento %d/3): %s", attempt + 1, exc)
                await asyncio.sleep(1.0 * (attempt + 1))
        log.error("Tarea queda en %s para recuperación al reiniciar", self.cfg.processing_queue)
        return False

    async def _store(self, task: Task, status: str, data: dict[str, Any]) -> None:
        payload = json.dumps({"id": task.id, "status": status, **data}, ensure_ascii=False)
        try:
            await self.redis.set(
                f"{self.cfg.result_prefix}{task.id}", payload, ex=self.cfg.result_ttl
            )
        except RedisError as exc:
            log.error("[%s] no se pudo guardar resultado: %s", task.id, exc)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


async def _amain() -> None:
    cfg = Config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    orch = Orchestrator(cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, orch.stop)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: orch.stop())
    await orch.run()


def main() -> None:
    try:
        asyncio.run(_amain())
    except RedisError as exc:
        print(f"No se pudo conectar a Redis: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
