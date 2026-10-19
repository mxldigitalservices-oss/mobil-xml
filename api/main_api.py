from __future__ import annotations
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import TaskRequest, TargetCreate
from api.routers.clones import router as clones_router
from identity.target_manager import TargetManager, TargetCategory
from infra.database import get_session
from infra.redis_client import get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Asegura schema de targets (en prod: Alembic)
    from infra.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await TargetManager(session).init_schema()
    yield


app = FastAPI(title="mobil-xml API", version="0.2.0", lifespan=lifespan)
app.include_router(clones_router)

QUEUE_NAME = "task_queue"  # legacy; los clones usan tasks:<id>


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/tasks", status_code=201)
async def enqueue_task(task: TaskRequest):
    try:
        r = get_redis()
        await r.lpush(QUEUE_NAME, json.dumps(task.model_dump()))
        return {"status": "queued", "task": task.model_dump()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/targets", status_code=201)
async def create_target(
    body: TargetCreate, session: AsyncSession = Depends(get_session)
):
    tm = TargetManager(session)
    target = await tm.add_target(body.url, TargetCategory(body.category), body.label)
    return {"id": target.id, "url": target.url, "category": target.category.value}


@app.get("/api/v1/targets")
async def list_targets(
    category: str, session: AsyncSession = Depends(get_session)
):
    tm = TargetManager(session)
    try:
        cat = TargetCategory(category)
    except ValueError as exc:
        raise HTTPException(400, f"categoría inválida: {category}") from exc
    rows = await tm.get_by_category(cat)
    return [{"id": t.id, "url": t.url, "label": t.label} for t in rows]
