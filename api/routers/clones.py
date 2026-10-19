from __future__ import annotations
import json
from fastapi import APIRouter

from api.schemas import BatchStartRequest, EmergencyStopRequest
from infra.redis_client import get_redis

router = APIRouter(prefix="/api/v1/clones", tags=["clones"])


@router.post("/batch-start")
async def batch_start(req: BatchStartRequest):
    r = get_redis()
    queued = 0
    for clone_id in req.clone_ids:
        task = {
            "task_id": f"{clone_id}:{queued}",
            "device_id": clone_id,
            "action": req.action,
            "payload": req.payload,
            "humanize": req.humanize,
            "media_type": req.media_type,
            "retries": 0,
            "resume_at": None,
        }
        await r.lpush(f"tasks:{clone_id}", json.dumps(task))
        queued += 1
    return {"queued": queued, "humanize": req.humanize, "media_type": req.media_type}


@router.post("/emergency-stop")
async def emergency_stop(req: EmergencyStopRequest):
    r = get_redis()
    targets = req.clone_ids or await r.smembers("active_clones")
    for clone_id in targets:
        await r.set(f"stop:{clone_id}", req.reason)
    return {"stopped": list(targets), "reason": req.reason}
