from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from api.main_api import app


def test_batch_start_enqueues_per_clone():
    fake = AsyncMock()
    with patch("api.routers.clones.get_redis", return_value=fake):
        with TestClient(app) as client:
            resp = client.post("/api/v1/clones/batch-start", json={
                "clone_ids": ["a", "b"],
                "humanize": True,
                "media_type": "audio",
                "action": "sleep",
                "payload": {},
            })
    assert resp.status_code == 200
    assert resp.json()["queued"] == 2
    assert fake.lpush.await_count == 2


def test_emergency_stop_sets_flags():
    fake = AsyncMock()
    with patch("api.routers.clones.get_redis", return_value=fake):
        with TestClient(app) as client:
            resp = client.post("/api/v1/clones/emergency-stop", json={
                "reason": "panic", "clone_ids": ["a", "b"]
            })
    assert resp.json()["stopped"] == ["a", "b"]
    assert fake.set.await_count == 2

