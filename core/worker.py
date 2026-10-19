from __future__ import annotations
import json
import logging
from dataclasses import dataclass

import redis.asyncio as aioredis

from core.orchestrator import OrchestratorEngine
from core.humanizer import HumanizeConfig

logger = logging.getLogger("Worker")
MAX_RETRIES = 3


@dataclass
class TaskError(Exception):
    task_id: str
    reason: str
    resume_at: str | None = None


class ResilientWorker:
    """
    Worker por instancia (aislamiento estricto): cada clone usa colas
    propias `tasks:<clone_id>` y `processing:<clone_id>`.
    """

    def __init__(self, redis_client: aioredis.Redis, clone_id: str, block_seconds: int = 5):
        self.redis = redis_client
        self.clone_id = clone_id
        self.queue = f"tasks:{clone_id}"
        self.processing = f"processing:{clone_id}"
        self.block_seconds = block_seconds

    async def consume_one(self) -> str | None:
        """BLMOVE atómico y bloqueante (Redis ≥ 6.2)."""
        return await self.redis.blmove(
            self.queue, self.processing, self.block_seconds, "RIGHT", "LEFT"
        )

    async def ack(self, raw: str) -> None:
        await self.redis.lrem(self.processing, 1, raw)

    async def nack(self, raw: str, error: TaskError) -> None:
        task = json.loads(raw)
        task["retries"] = task.get("retries", 0) + 1
        task["resume_at"] = error.resume_at
        await self.redis.lrem(self.processing, 1, raw)
        if task["retries"] > MAX_RETRIES:
            logger.error(f"[{self.clone_id}] dead-letter task={task.get('task_id')}")
            await self.redis.lpush(f"dead:{self.clone_id}", json.dumps(task))
            return
        await self.redis.lpush(self.queue, json.dumps(task))

    async def process(self, raw: str) -> None:
        task = json.loads(raw)
        engine = OrchestratorEngine(
            device_id=self.clone_id,
            config=HumanizeConfig(
                humanize=task.get("humanize", True),
                media_type=task.get("media_type", "video"),
            ),
        )
        try:
            if not engine.connect_adb():
                raise TaskError(task.get("task_id", "?"), "adb_connect_failed")
            engine.execute_action(task["action"], task.get("payload", {}))
            await self.ack(raw)
        except TaskError as exc:
            await self.nack(raw, exc)
        except Exception as exc:  # noqa: BLE001
            await self.nack(raw, TaskError(task.get("task_id", "?"), str(exc)))

    async def run_forever(self) -> None:
        while True:
            raw = await self.consume_one()
            if raw is None:
                continue
            await self.process(raw)
