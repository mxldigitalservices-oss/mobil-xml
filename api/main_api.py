"""
mobil-xml / api / main_api.py

Servidor FastAPI:
  - API REST para el futuro frontend web (protegida con API key + rate limit).
  - Webhooks de WhatsApp Cloud API (verificación GET + recepción POST firmada).
  - Estado compartido (bandeja y deduplicación) en Redis: sobrevive a reinicios
    y funciona con varios workers de uvicorn.

Variables de entorno:
  ENVIRONMENT, LOG_LEVEL, API_KEY (>=32 chars en producción), CORS_ORIGINS,
  ALLOWED_HOSTS, REDIS_URL, WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET,
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, SEND_RATE_PER_MINUTE,
  SEND_RATE_PER_RECIPIENT_HOUR, MAX_WEBHOOK_BODY_BYTES, INBOX_TTL_SECONDS,
  DEDUP_TTL_SECONDS.

Ejecución (desde la raíz del repo):
  uvicorn api.main_api:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
import redis.asyncio as aioredis
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.exceptions import RedisError


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "production"
    log_level: str = "INFO"

    # Frontend
    api_key: str = ""  # Clave que el frontend envía en el header X-API-Key
    cors_origins: str = ""  # Lista separada por comas
    allowed_hosts: str = ""  # Lista separada por comas (vacío = sin restricción)

    # Estado compartido
    redis_url: str = "redis://localhost:6379/0"
    inbox_ttl_seconds: int = 7 * 24 * 3600
    dedup_ttl_seconds: int = 24 * 3600

    # Límites
    max_webhook_body_bytes: int = 1_048_576
    send_rate_per_minute: int = 30
    send_rate_per_recipient_hour: int = 10

    # WhatsApp Cloud API (Meta)
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    graph_api_version: str = "v21.0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("mobil-xml.api")

MAX_STORED_MESSAGES = 500
INBOX_KEY = "mobil:api:inbox"
SEEN_PREFIX = "mobil:api:seen:"
MIN_API_KEY_LEN = 32


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _safe_equals(a: str, b: str) -> bool:
    """Comparación en tiempo constante que NO falla con caracteres no ASCII."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


# --------------------------------------------------------------------------- #
# Ciclo de vida
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.is_production and len(settings.api_key) < MIN_API_KEY_LEN:
        raise RuntimeError(
            f"API_KEY es obligatoria y debe tener al menos {MIN_API_KEY_LEN} caracteres en producción"
        )

    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=5,
        health_check_interval=30,
    )
    try:
        await app.state.redis.ping()
    except RedisError as exc:
        # Arranca degradado: /ready devolverá 503 y las rutas con estado también.
        logger.error("Redis no disponible al iniciar: %s", exc)

    missing = [
        name
        for name, value in {
            "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token,
            "WHATSAPP_APP_SECRET": settings.whatsapp_app_secret,
            "WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
            "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
        }.items()
        if not value
    ]
    if missing:
        logger.warning("Variables de entorno sin configurar: %s", ", ".join(missing))
    logger.info("API iniciada (entorno=%s)", settings.environment)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()
        logger.info("API detenida")


app = FastAPI(
    title="mobil-xml API",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

if settings.allowed_hosts_list:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[*settings.allowed_hosts_list, "127.0.0.1", "localhost"],
    )

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=600,
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError) -> JSONResponse:
    logger.error("Error de Redis en %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Almacén de estado no disponible"},
    )


# --------------------------------------------------------------------------- #
# Seguridad
# --------------------------------------------------------------------------- #
async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key no configurada")
    if not x_api_key or not _safe_equals(x_api_key, settings.api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key inválida")


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Valida X-Hub-Signature-256 (HMAC-SHA256 con el App Secret de Meta)."""
    if not settings.whatsapp_app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return _safe_equals(expected, signature_header.removeprefix("sha256="))


async def rate_limit(redis: aioredis.Redis, scope: str, limit: int, window: int) -> None:
    """Ventana fija en Redis. Lanza 429 si se supera `limit` en `window` segundos."""
    if limit <= 0:
        return
    now = int(time.time())
    key = f"mobil:api:rl:{scope}:{now // window}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window + 5)
        count, _ = await pipe.execute()
    if count > limit:
        retry_after = window - (now % window)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiadas solicitudes",
            headers={"Retry-After": str(retry_after)},
        )


async def read_limited_body(request: Request, limit: int) -> bytes:
    """Lee el cuerpo abortando si supera `limit` bytes (antes de validar la firma)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(413, "Cuerpo demasiado grande")
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Length inválido") from exc
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "Cuerpo demasiado grande")
        chunks.append(chunk)
    return b"".join(chunks)


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(..., pattern=r"^\d{8,15}$", description="Número en formato internacional, solo dígitos")
    text: str = Field(..., min_length=1, max_length=4096)


class SendMessageResponse(BaseModel):
    status: str
    message_id: str | None = None


# --------------------------------------------------------------------------- #
# WhatsApp: cliente y procesamiento
# --------------------------------------------------------------------------- #
def _graph_error_summary(resp: httpx.Response) -> str:
    """Resumen seguro del error de Meta (sin volcar el cuerpo, que puede traer datos personales)."""
    try:
        err = _as_dict(_as_dict(resp.json()).get("error"))
        return f"code={err.get('code')} type={err.get('type')}"
    except ValueError:
        return "cuerpo no JSON"


async def send_whatsapp_text(client: httpx.AsyncClient, to: str, text: str) -> dict[str, Any]:
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp no configurado")

    url = f"{settings.graph_url}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    try:
        resp = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except httpx.HTTPError as exc:
        logger.error("Error de red con WhatsApp: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo contactar a WhatsApp") from exc

    if resp.status_code >= 400:
        logger.error("WhatsApp respondió %s (%s)", resp.status_code, _graph_error_summary(resp))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "WhatsApp rechazó la solicitud")
    try:
        return _as_dict(resp.json())
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Respuesta inválida de WhatsApp") from exc


async def process_incoming_message(
    redis: aioredis.Redis, message: dict[str, Any], contact_name: str | None
) -> None:
    """
    Punto de extensión: aquí se conecta la lógica de negocio de mobil-xml
    (parseo/generación de XML, respuestas automáticas, etc.).
    """
    msg_type = message.get("type", "unknown")
    body = _as_dict(message.get("text")).get("body") if msg_type == "text" else None
    record = {
        "id": message.get("id"),
        "from": message.get("from"),
        "name": contact_name,
        "type": msg_type,
        "text": body[:4096] if isinstance(body, str) else None,
        "timestamp": message.get("timestamp"),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lpush(INBOX_KEY, json.dumps(record, ensure_ascii=False))
        pipe.ltrim(INBOX_KEY, 0, MAX_STORED_MESSAGES - 1)
        pipe.expire(INBOX_KEY, settings.inbox_ttl_seconds)
        await pipe.execute()
    logger.info("Mensaje entrante id=%s tipo=%s", record["id"], msg_type)


async def handle_webhook_payload(redis: aioredis.Redis, payload: dict[str, Any]) -> None:
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(_as_dict(entry).get("changes")):
            value = _as_dict(_as_dict(change).get("value"))

            contacts: dict[Any, Any] = {}
            for c in _as_list(value.get("contacts")):
                c = _as_dict(c)
                contacts[c.get("wa_id")] = _as_dict(c.get("profile")).get("name")

            for message in _as_list(value.get("messages")):
                message = _as_dict(message)
                msg_id = message.get("id")
                if not isinstance(msg_id, str) or not msg_id or len(msg_id) > 256:
                    continue
                seen_key = f"{SEEN_PREFIX}{msg_id}"
                try:
                    # Deduplicación atómica: solo el primero que la reclama procesa el mensaje.
                    claimed = await redis.set(seen_key, "1", nx=True, ex=settings.dedup_ttl_seconds)
                    if not claimed:
                        continue
                    try:
                        await process_incoming_message(
                            redis, message, contacts.get(message.get("from"))
                        )
                    except Exception:  # noqa: BLE001 - nunca romper el lote completo
                        logger.exception("Error procesando mensaje %s", msg_id)
                        # Libera la marca para que un reenvío de Meta pueda reintentarlo.
                        await redis.delete(seen_key)
                except RedisError as exc:
                    logger.error("Redis falló procesando mensaje %s: %s", msg_id, exc)

            for st in _as_list(value.get("statuses")):
                st = _as_dict(st)
                logger.info("Estado mensaje id=%s -> %s", st.get("id"), st.get("status"))


# --------------------------------------------------------------------------- #
# Rutas públicas / salud
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["sistema"])
async def health() -> dict[str, str]:
    """Liveness: el proceso responde."""
    return {"status": "ok"}


@app.get("/ready", tags=["sistema"])
async def ready(request: Request) -> dict[str, str]:
    """Readiness: dependencias críticas (Redis) accesibles."""
    await _redis(request).ping()
    return {"status": "ready"}


# --------------------------------------------------------------------------- #
# Webhooks de WhatsApp
# --------------------------------------------------------------------------- #
@app.get("/webhooks/whatsapp", response_class=PlainTextResponse, tags=["whatsapp"])
async def whatsapp_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> str:
    """Handshake de verificación de Meta."""
    if (
        hub_mode == "subscribe"
        and hub_challenge is not None
        and settings.whatsapp_verify_token
        and hub_verify_token
        and _safe_equals(hub_verify_token, settings.whatsapp_verify_token)
    ):
        return hub_challenge
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verificación fallida")


@app.post("/webhooks/whatsapp", tags=["whatsapp"])
async def whatsapp_receive(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> Response:
    """Recibe eventos de Meta. Responde 200 rápido y procesa en segundo plano."""
    raw_body = await read_limited_body(request, settings.max_webhook_body_bytes)

    if not verify_meta_signature(raw_body, x_hub_signature_256):
        logger.warning("Webhook rechazado: firma inválida")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Firma inválida")

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON inválido") from exc

    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    # Si Redis está caído devolvemos 503 (vía exception handler) para que Meta reintente,
    # en lugar de confirmar con 200 un evento que se perdería.
    redis = _redis(request)
    await redis.ping()

    background.add_task(handle_webhook_payload, redis, payload)
    return Response(status_code=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# API para el frontend web
# --------------------------------------------------------------------------- #
@app.post(
    "/api/v1/messages/send",
    response_model=SendMessageResponse,
    dependencies=[Depends(require_api_key)],
    tags=["frontend"],
)
async def send_message(body: SendMessageRequest, request: Request) -> SendMessageResponse:
    redis = _redis(request)
    await rate_limit(redis, "send:global", settings.send_rate_per_minute, 60)
    recipient = hashlib.sha256(body.to.encode()).hexdigest()[:16]
    await rate_limit(redis, f"send:to:{recipient}", settings.send_rate_per_recipient_hour, 3600)

    data = await send_whatsapp_text(request.app.state.http, body.to, body.text)
    msg_id = (data.get("messages") or [{}])[0].get("id")
    return SendMessageResponse(status="sent", message_id=msg_id)


@app.get(
    "/api/v1/messages",
    dependencies=[Depends(require_api_key)],
    tags=["frontend"],
)
async def list_messages(
    request: Request,
    limit: int = Query(default=50, ge=1, le=MAX_STORED_MESSAGES),
) -> dict[str, Any]:
    raw_items = await _redis(request).lrange(INBOX_KEY, 0, limit - 1)  # más recientes primero
    items: list[Any] = []
    for raw in raw_items:
        try:
            items.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("Registro de bandeja corrupto omitido")
    return {"count": len(items), "messages": items}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main_api:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
    )
