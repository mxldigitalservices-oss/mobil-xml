import json
import fakeredis.aioredis
import pytest

from core.worker import ResilientWorker, TaskError


@pytest.fixture
async def redis_client():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def test_blmove_moves_atomically(redis_client):
    w = ResilientWorker(redis_client, clone_id="emu-1")
    await redis_client.lpush(w.queue, '{"task_id":"1"}')
    raw = await w.consume_one()
    assert raw is not None
    assert await redis_client.llen(w.queue) == 0
    assert await redis_client.llen(w.processing) == 1


async def test_nack_requeues_with_resume_at(redis_client):
    w = ResilientWorker(redis_client, clone_id="emu-1")
    raw = '{"task_id":"2","retries":0}'
    await redis_client.lpush(w.processing, raw)
    await w.nack(raw, TaskError("2", "boom", resume_at="step_3"))
    requeued = await redis_client.lindex(w.queue, 0)
    data = json.loads(requeued)
    assert data["resume_at"] == "step_3"
    assert data["retries"] == 1


async def test_nack_exceeds_retries_goes_to_deadletter(redis_client):
    w = ResilientWorker(redis_client, clone_id="emu-1")
    raw = '{"task_id":"3","retries":3}'
    await redis_client.lpush(w.processing, raw)
    await w.nack(raw, TaskError("3", "boom"))
    assert await redis_client.llen(w.queue) == 0
    assert await redis_client.llen(f"dead:emu-1") == 1
