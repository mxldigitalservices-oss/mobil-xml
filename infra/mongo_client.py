from __future__ import annotations
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://mobil_admin:mobil_password@localhost:27017/?authSource=admin"
)

_client: AsyncIOMotorClient | None = None

def get_mongo_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URL)
    return _client

def get_mongo_db(db_name: str = "mobil_logs_db"):
    client = get_mongo_client()
    return client[db_name]
