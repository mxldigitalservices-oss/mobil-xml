import asyncio
import json

import fakeredis
import pytest

from core.orchestrator import AdbError, Config, Orchestrator, Task, TaskError

GOOD = {
    "id": "t1",
    "device": "redroid-1:5555",
    "actions": [
        {"type": "tap", "x": 10, "y": 20},
        {"type": "key", "key": "KEYCODE_ENTER"},
        {"type": "wait", "min": 0, "max": 0},
    ],
}


def cfg(**kw):
    base = dict(
        queue="q", dead_queue="dead", processing_prefix="proc:", instance_id="i1",
        poll_timeout=1, workers=1, max_attempts=3, retry_backoff=0.01,
        task_timeout=5, min_delay=0, max_delay=0, allowed_devices=(),
        heartbeat_path="/tmp/test-alive",
    )
    base.update(kw)
    return Config(**base)


def make(**kw):
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    o = Orchestrator(cfg(**kw), redis=r)
    return o, r


# ---------- validación ----------
@pytest.mark.parametrize("mutate", [
    lambda d: d.update(attempts="x"),                       # antes mataba al worker
    lambda d: d.update(device="a b; rm -rf /"),
    lambda d: d.update(actions=[{"type": "tap", "x": "abc", "y": 1}]),
    lambda d: d.update(actions=[{"type": "tap", "x": 99999999, "y": 1}]),
    lambda d: d.update(actions=[{"type": "wait", "min": 5, "max": 1}]),
    lambda d: d.update(actions=[{"type": "wait", "min": 1e9, "max": 1e9}]),
    lambda d: d.update(actions=[{"type": "boom"}]),
    lambda d: d.update(actions=[{"type": "open_app", "package": "x; reboot"}]),
    lambda d: d.update(id="../../etc"),
    lambda d: d.update(locale="es DO'; DROP"),
    lambda d: d.update(actions=[{"type": "tap", "x": 1, "y": 1}] * 500),
])
def test_invalid_tasks_raise_taskerror_only(mutate):
    d = json.loads(json.dumps(GOOD))
    mutate(d)
    with pytest.raises(TaskError):
        Task.parse(json.dumps(d))


def test_not_json_and_not_object():
    for raw in ("{", "[]", "null", "x" * 70000):
        with pytest.raises(TaskError):
            Task.parse(raw)


def test_device_allowlist():
    with pytest.raises(TaskError):
        Task.parse(json.dumps(GOOD), ("redroid-2:5555",))
    assert Task.parse(json.dumps(GOOD), ("redroid-1:5555",)).id == "t1"


# ---------- cola fiable y workers ----------
async def run_worker_until_idle(o, r, seconds=2.0):
    w = asyncio.create_task(o._worker(0))
    await asyncio.sleep(seconds)
    o._stop.set()
    await asyncio.wait_for(w, 5)


async def test_poison_messages_do_not_kill_worker():
    o, r = make()
    calls = []

    async def fake_shell(serial, cmd):
        calls.append(cmd)
        return ""
    o.adb.shell = fake_shell
    await r.rpush("q", '{"device":"redroid-1:5555","attempts":"x","actions":[{"type":"key","key":"4"}]}')
    await r.rpush("q", "no es json")
    await r.rpush("q", json.dumps(GOOD))
    await run_worker_until_idle(o, r)
    assert len(calls) == 2                      # la tarea buena sí se ejecutó
    assert await r.llen("dead") == 2            # las 2 malas fueron a dead-letter
    assert await r.llen("proc:i1") == 0         # nada quedó colgado
    res = json.loads(await r.get("mobil:result:t1"))
    assert res["status"] == "ok"


async def test_retry_resumes_without_repeating_done_actions():
    o, r = make()
    seen = []
    state = {"fail": True}

    async def fake_shell(serial, cmd):
        seen.append(cmd)
        if "keyevent" in cmd and state["fail"]:
            state["fail"] = False
            raise AdbError("boom")
        return ""
    o.adb.shell = fake_shell
    await r.rpush("q", json.dumps(GOOD))
    await run_worker_until_idle(o, r, 2.5)
    taps = [c for c in seen if c.startswith("input swipe")]
    keys = [c for c in seen if "keyevent" in c]
    assert len(taps) == 1, seen                 # el tap NO se repitió
    assert len(keys) == 2                       # el key fallido sí se reintentó
    assert json.loads(await r.get("mobil:result:t1"))["status"] == "ok"


async def test_exhausted_attempts_go_to_dead_letter():
    o, r = make(max_attempts=2)

    async def always_fail(serial, cmd):
        raise AdbError("down")
    o.adb.shell = always_fail
    await r.rpush("q", json.dumps(GOOD))
    await run_worker_until_idle(o, r, 2.5)
    assert await r.llen("dead") == 1
    assert await r.llen("proc:i1") == 0
    assert json.loads(await r.get("mobil:result:t1"))["status"] == "failed"


async def test_recover_after_crash():
    o, r = make()
    await r.rpush("proc:i1", json.dumps(GOOD))  # quedó en processing por una caída
    assert await o.recover_processing() == 1
    assert await r.llen("q") == 1 and await r.llen("proc:i1") == 0


async def test_redis_failure_in_finish_does_not_kill_worker(monkeypatch):
    o, r = make()
    o.adb.shell = lambda s, c: asyncio.sleep(0, "")

    async def flaky(*a, **k):
        raise RuntimeError("inesperado")
    o._finish = flaky
    await r.rpush("q", json.dumps(GOOD))
    await r.rpush("q", json.dumps({**GOOD, "id": "t2"}))
    await run_worker_until_idle(o, r, 2.5)
    # el worker sobrevivió y procesó ambas (los resultados se guardan antes de _finish)
    assert await r.get("mobil:result:t1") and await r.get("mobil:result:t2")
