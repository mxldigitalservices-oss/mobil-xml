import hashlib
import hmac
import json
import os

os.environ.update(ENVIRONMENT="development", API_KEY="k" * 40, WHATSAPP_APP_SECRET="s3cret",
                  WHATSAPP_VERIFY_TOKEN="vtok", SEND_RATE_PER_MINUTE="3",
                  SEND_RATE_PER_RECIPIENT_HOUR="2", MAX_WEBHOOK_BODY_BYTES="2000")

import fakeredis
import pytest
from fastapi.testclient import TestClient

from api import main_api as m


@pytest.fixture()
def client(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(m.aioredis, "from_url", lambda *a, **k: fake)

    async def fake_send(client, to, text):
        return {"messages": [{"id": "wamid.X"}]}
    monkeypatch.setattr(m, "send_whatsapp_text", fake_send)
    with TestClient(m.app) as c:
        yield c


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()


def wa_payload(msg_id="m1"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "18095551234", "profile": {"name": "Ana"}}],
        "messages": [{"id": msg_id, "from": "18095551234", "type": "text",
                      "text": {"body": "hola"}, "timestamp": "1"}]}}]}]}


def test_health_ready(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").json() == {"status": "ready"}


def test_non_ascii_api_key_is_401_not_500(client):
    r = client.get("/api/v1/messages", headers={"X-API-Key": "ñandú".encode("latin-1")})
    assert r.status_code == 401


def test_non_ascii_verify_token_is_403_not_500(client):
    r = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "ñ✓", "hub.challenge": "c"})
    assert r.status_code == 403
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "vtok", "hub.challenge": "c"})
    assert ok.status_code == 200 and ok.text == "c"


def test_webhook_signature_dedup_and_inbox(client):
    body = json.dumps(wa_payload()).encode()
    assert client.post("/webhooks/whatsapp", content=body).status_code == 403
    h = {"X-Hub-Signature-256": sign(body)}
    assert client.post("/webhooks/whatsapp", content=body, headers=h).status_code == 200
    assert client.post("/webhooks/whatsapp", content=body, headers=h).status_code == 200  # reenvío
    msgs = client.get("/api/v1/messages", headers={"X-API-Key": "k" * 40}).json()
    assert msgs["count"] == 1 and msgs["messages"][0]["text"] == "hola"


def test_webhook_body_limit(client):
    big = b"x" * 5000
    assert client.post("/webhooks/whatsapp", content=big, headers={"X-Hub-Signature-256": sign(big)}).status_code == 413


def test_webhook_garbage_shapes_do_not_crash(client):
    body = json.dumps({"object": "whatsapp_business_account", "entry": [1, {"changes": "x"}, {"changes": [{"value": {"messages": [5, {"id": 7}]}}]}]}).encode()
    assert client.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": sign(body)}).status_code == 200


def test_send_requires_key_and_rate_limits(client):
    h = {"X-API-Key": "k" * 40}
    assert client.post("/api/v1/messages/send", json={"to": "18095551234", "text": "a"}).status_code == 401
    assert client.post("/api/v1/messages/send", json={"to": "18095551234", "text": "a", "x": 1}, headers=h).status_code == 422
    codes = [client.post("/api/v1/messages/send", json={"to": "18095551234", "text": "a"}, headers=h).status_code for _ in range(3)]
    assert codes == [200, 200, 429]   # límite por destinatario = 2/hora
