#!/usr/bin/env python3
"""mobil-xml · core/orchestrator.py

Orquestador asíncrono:
  * Consume tareas JSON desde una cola Redis (BLPOP).
  * Usa la API local de Ollama para generar texto con acento regional / nicho.
  * Ejecuta comandos ADB "humanizados" (jitter, pausas variables, tecleo por
    fragmentos) sobre uno o varios emuladores, serializando el acceso por
    dispositivo.

Formato de tarea (JSON en la lista Redis ``REDIS_QUEUE``)::

    {
      "id": "tarea-001",
      "device": "emulator-5554",
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
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shlex
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Config:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue: str = os.getenv("REDIS_QUEUE", "mobil:tasks")
    dead_queue: str = os.getenv("REDIS_DEAD_QUEUE", "mobil:tasks:dead")
    result_prefix: str = os.getenv("REDIS_RESULT_PREFIX", "mobil:result:")
    result_ttl: int = _env_int("RESULT_TTL_SECONDS", 86400)
    poll_timeout: int = _env_int("REDIS_POLL_TIMEOUT", 5)

    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    ollama_timeout: float = _env_float("OLLAMA_TIMEOUT", 120.0)
    ollama_retries: int = _env_int("OLLAMA_RETRIES", 2)

    adb_path: str = os.getenv("ADB_PATH", "adb")
    adb_timeout: float = _env_float("ADB_TIMEOUT", 20.0)
    ime_id: str = os.getenv("ADB_IME_ID", "com.android.adbkeyboard/.AdbIME")

    workers: int = _env_int("WORKERS", 4)
    max_attempts: int = _env_int("MAX_ATTEMPTS", 3)
    retry_backoff: float = _env_float("RETRY_BACKOFF", 5.0)
    task_timeout: float = _env_float("TASK_TIMEOUT", 300.0)
    shutdown_grace: float = _env_float("SHUTDOWN_GRACE", 30.0)

    min_delay: float = _env_float("HUMAN_MIN_DELAY", 0.4)
    max_delay: float = _env_float("HUMAN_MAX_DELAY", 1.8)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_KEY_RE = re.compile(r"^(KEYCODE_[A-Z0-9_]+|\d{1,3})$")


class TaskError(Exception):
    """Tarea inválida: no se reintenta."""


class AdbError(Exception):
    """Fallo al ejecutar ADB: se reintenta."""


class OllamaError(Exception):
    """Fallo al hablar con Ollama: se reintenta."""


@dataclass
class Task:
    id: str
    device: str
    actions: list[dict[str, Any]]
    locale: str = "es-DO"
    niche: str = "general"
    attempts: int = 0

    @classmethod
    def parse(cls, raw: str) -> "Task":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaskError(f"JSON inválido: {exc}") from exc
        if not isinstance(data, dict):
            raise TaskError("La tarea debe ser un objeto JSON")

        device = str(data.get("device", ""))
        if not _SERIAL_RE.match(device):
            raise TaskError(f"Serial de dispositivo inválido: {device!r}")

        actions = data.get("actions")
        if not isinstance(actions, list) or not actions:
            raise TaskError("'actions' debe ser una lista no vacía")
        for i, act in enumerate(actions):
            if not isinstance(act, dict) or "type" not in act:
                raise TaskError(f"Acción #{i} inválida")

        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            device=device,
            actions=actions,
            locale=str(data.get("locale", "es-DO")),
            niche=str(data.get("niche", "general")),
            attempts=int(data.get("attempts", 0)),
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

    async def run(self, serial: str, *args: str) -> str:
        cmd = [self.cfg.adb_path, "-s", serial, *args]
        log.debug("ADB: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=self.cfg.adb_timeout
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise AdbError(f"Timeout ADB en {serial}: {args}") from exc
        except FileNotFoundError as exc:
            raise AdbError(f"No se encontró el binario ADB: {self.cfg.adb_path}") from exc

        if proc.returncode != 0:
            raise AdbError(
                f"ADB falló ({proc.returncode}) en {serial}: "
                f"{err.decode(errors='replace').strip()}"
            )
        return out.decode(errors="replace").strip()

    async def shell(self, serial: str, command: str) -> str:
        return await self.run(serial, "shell", command)


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
            except (httpx.HTTPError, KeyError, ValueError, OllamaError) as exc:
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
    log: list[str] = field(default_factory=list)


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
        for i, act in enumerate(ctx.task.actions):
            kind = act["type"]
            handler = self._handlers.get(kind)
            if handler is None:
                raise TaskError(f"Acción desconocida: {kind!r}")
            log.info("[%s] %s #%d → %s", ctx.task.id, ctx.task.device, i, kind)
            await handler(ctx, act)
            ctx.log.append(kind)
            if kind not in ("wait", "generate"):
                await self.human.pause()

    # -- acciones ----------------------------------------------------------

    @staticmethod
    def _int(act: dict, key: str) -> int:
        try:
            return int(act[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskError(f"Parámetro entero requerido: {key!r}") from exc

    async def _tap(self, ctx: RunContext, act: dict) -> None:
        x = self.human.jitter(self._int(act, "x"))
        y = self.human.jitter(self._int(act, "y"))
        long_ms = int(act.get("long_press_ms", 0))
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
        dur = int(act.get("duration_ms") or random.randint(250, 650))
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
        lo = float(act.get("min", 1.0))
        hi = float(act.get("max", max(lo, 3.0)))
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
            max_chars=int(act.get("max_chars", 200)),
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
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.redis = aioredis.from_url(cfg.redis_url, decode_responses=True)
        self.ollama = OllamaClient(cfg)
        self.executor = DeviceExecutor(cfg, Adb(cfg), self.ollama, Humanizer(cfg))
        self._locks: dict[str, asyncio.Lock] = {}
        self._stop = asyncio.Event()

    def stop(self) -> None:
        log.info("Señal de parada recibida; cerrando de forma ordenada…")
        self._stop.set()

    def _lock(self, device: str) -> asyncio.Lock:
        return self._locks.setdefault(device, asyncio.Lock())

    async def run(self) -> None:
        await self.redis.ping()
        log.info(
            "Orquestador listo · cola=%s · workers=%d · modelo=%s",
            self.cfg.queue, self.cfg.workers, self.cfg.ollama_model,
        )
        workers = [asyncio.create_task(self._worker(n)) for n in range(self.cfg.workers)]
        await self._stop.wait()
        _, pending = await asyncio.wait(workers, timeout=self.cfg.shutdown_grace)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.ollama.close()
        await self.redis.aclose()
        log.info("Orquestador detenido")

    async def _worker(self, n: int) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                item = await self.redis.blpop(self.cfg.queue, timeout=self.cfg.poll_timeout)
                backoff = 1.0
            except RedisError as exc:
                log.error("Redis error (worker %d): %s", n, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            if item is None:
                continue
            await self._handle(item[1])

    async def _handle(self, raw: str) -> None:
        try:
            task = Task.parse(raw)
        except TaskError as exc:
            log.error("Tarea descartada: %s", exc)
            await self._dead(raw, str(exc))
            return

        started = time.monotonic()
        try:
            async with self._lock(task.device):
                ctx = RunContext(task=task)
                await asyncio.wait_for(self.executor.execute(ctx), timeout=self.cfg.task_timeout)
            await self._store(task, "ok", {"actions": ctx.log, "generated": ctx.generated,
                                           "elapsed": round(time.monotonic() - started, 2)})
            log.info("[%s] completada en %.1fs", task.id, time.monotonic() - started)
        except TaskError as exc:
            log.error("[%s] tarea inválida: %s", task.id, exc)
            await self._store(task, "invalid", {"error": str(exc)})
            await self._dead(raw, str(exc))
        except (AdbError, OllamaError, asyncio.TimeoutError, RedisError) as exc:
            await self._retry(task, exc)
        except Exception:  # noqa: BLE001 - nunca tumbar el worker
            log.exception("[%s] error inesperado", task.id)
            await self._retry(task, RuntimeError("error inesperado"))

    async def _retry(self, task: Task, exc: Exception) -> None:
        task.attempts += 1
        if task.attempts >= self.cfg.max_attempts:
            log.error("[%s] agotados los intentos: %s", task.id, exc)
            await self._store(task, "failed", {"error": str(exc), "attempts": task.attempts})
            await self._dead(task.to_json(), str(exc))
            return
        delay = self.cfg.retry_backoff * (2 ** (task.attempts - 1))
        log.warning("[%s] reintento %d/%d en %.0fs: %s",
                    task.id, task.attempts, self.cfg.max_attempts, delay, exc)
        await asyncio.sleep(delay)
        await self.redis.rpush(self.cfg.queue, task.to_json())

    async def _store(self, task: Task, status: str, data: dict[str, Any]) -> None:
        payload = json.dumps({"id": task.id, "status": status, **data}, ensure_ascii=False)
        try:
            await self.redis.set(
                f"{self.cfg.result_prefix}{task.id}", payload, ex=self.cfg.result_ttl
            )
        except RedisError as exc:
            log.error("[%s] no se pudo guardar resultado: %s", task.id, exc)

    async def _dead(self, raw: str, reason: str) -> None:
        try:
            await self.redis.rpush(
                self.cfg.dead_queue,
                json.dumps({"reason": reason, "task": raw}, ensure_ascii=False),
            )
        except RedisError as exc:
            log.error("No se pudo enviar a dead-letter: %s", exc)


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
