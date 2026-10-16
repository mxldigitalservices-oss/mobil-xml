"""
mobil-xml / api / main_api.py

Servidor FastAPI:
  - API REST para el futuro frontend web (protegida con API key).
  - Webhooks de WhatsApp Cloud API (verificación GET + recepción POST firmada).

Variables de entorno (ver README / bloque Settings):
  WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_ACCESS_TOKEN,
  WHATSAPP_PHONE_NUMBER_ID, API_KEY, CORS_ORIGINS, ENVIRONMENT, LOG_LEVEL

Ejecución (desde la raíz del repo):
  uvicorn api.main_api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
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
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"


settings = Settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("mobil-xml.api")


# --------------------------------------------------------------------------- #
# Estado en memoria (reemplazar por BD/cola en escala)
# --------------------------------------------------------------------------- #
MAX_STORED_MESSAGES = 500
MAX_SEEN_IDS = 5000

inbox: deque[dict[str, Any]] = deque(maxlen=MAX_STORED_MESSAGES)
seen_message_ids: OrderedDict[str, None] = OrderedDict()


def _already_seen(message_id: str) -> bool:
    """Deduplicación: Meta puede reenviar el mismo evento."""
    if message_id in seen_message_ids:
        return True
    seen_message_ids[message_id] = None
    if len(seen_message_ids) > MAX_SEEN_IDS:
        seen_message_ids.popitem(last=False)
    return False


# --------------------------------------------------------------------------- #
# Ciclo de vida
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    missing = [
        name
        for name, value in {
            "API_KEY": settings.api_key,
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
        logger.info("API detenida")


app = FastAPI(
    title="mobil-xml API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=600,
    )


# --------------------------------------------------------------------------- #
# Seguridad
# --------------------------------------------------------------------------- #
async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key no configurada")
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
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
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class SendMessageRequest(BaseModel):
    to: str = Field(..., pattern=r"^\d{8,15}$", description="Número en formato internacional, solo dígitos")
    text: str = Field(..., min_length=1, max_length=4096)


class SendMessageResponse(BaseModel):
    status: str
    message_id: str | None = None


# --------------------------------------------------------------------------- #
# WhatsApp: cliente y procesamiento
# --------------------------------------------------------------------------- #
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
        logger.error("Error de red con WhatsApp: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo contactar a WhatsApp") from exc

    if resp.status_code >= 400:
        logger.error("WhatsApp respondió %s: %s", resp.status_code, resp.text[:500])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "WhatsApp rechazó la solicitud")
    return resp.json()


async def process_incoming_message(
    client: httpx.AsyncClient, message: dict[str, Any], contact_name: str | None
) -> None:
    """
    Punto de extensión: aquí se conecta la lógica de negocio de mobil-xml
    (parseo/generación de XML, respuestas automáticas, etc.).
    """
    msg_type = message.get("type", "unknown")
    record = {
        "id": message.get("id"),
        "from": message.get("from"),
        "name": contact_name,
        "type": msg_type,
        "text": message.get("text", {}).get("body") if msg_type == "text" else None,
        "timestamp": message.get("timestamp"),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    inbox.append(record)
    logger.info("Mensaje entrante id=%s tipo=%s", record["id"], msg_type)


async def handle_webhook_payload(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                c.get("wa_id"): c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                msg_id = message.get("id")
                if not msg_id or _already_seen(msg_id):
                    continue
                try:
                    await process_incoming_message(
                        client, message, contacts.get(message.get("from"))
                    )
                except Exception:  # noqa: BLE001 - nunca romper el lote completo
                    logger.exception("Error procesando mensaje %s", msg_id)
            for st in value.get("statuses", []):
                logger.info("Estado mensaje id=%s -> %s", st.get("id"), st.get("status"))


# --------------------------------------------------------------------------- #
# Rutas públicas / salud
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["sistema"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
        and secrets.compare_digest(hub_verify_token, settings.whatsapp_verify_token)
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
    raw_body = await request.body()

    if not verify_meta_signature(raw_body, x_hub_signature_256):
        logger.warning("Webhook rechazado: firma inválida")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Firma inválida")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON inválido") from exc

    if payload.get("object") != "whatsapp_business_account":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    background.add_task(handle_webhook_payload, request.app.state.http, payload)
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
    data = await send_whatsapp_text(request.app.state.http, body.to, body.text)
    msg_id = (data.get("messages") or [{}])[0].get("id")
    return SendMessageResponse(status="sent", message_id=msg_id)


@app.get(
    "/api/v1/messages",
    dependencies=[Depends(require_api_key)],
    tags=["frontend"],
)
async def list_messages(limit: int = Query(default=50, ge=1, le=MAX_STORED_MESSAGES)) -> dict[str, Any]:
    items = list(inbox)[-limit:]
    items.reverse()  # más recientes primero
    return {"count": len(items), "messages": items}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main_api:app", host="0.0.0.0", port=8000)
