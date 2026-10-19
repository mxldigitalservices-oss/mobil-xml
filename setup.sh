#!/bin/bash
set -e

echo "📁 Creando estructura de directorios para mobil-xml..."
mkdir -p infra core identity api/routers tests

echo "📄 Escribiendo archivos de configuración raíz..."
cat << 'FILE_EOF' > requirements.txt
fastapi>=0.100.0
uvicorn>=0.22.0
pydantic>=2.0
redis>=5.0.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.28.0
faker>=19.0.0
pytest>=7.0.0
pytest-asyncio>=0.21.0
fakeredis>=2.18.0
httpx>=0.24.0
FILE_EOF

cat << 'FILE_EOF' > pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
FILE_EOF

echo "📄 Escribiendo módulos de infra..."
cat << 'FILE_EOF' > infra/database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://mobil_user:mobil_password@localhost:5432/mobil_db"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_session():
    async with AsyncSessionLocal() as session:
        yield session
FILE_EOF

cat << 'FILE_EOF' > infra/redis_client.py
import os
import redis.asyncio as aioredis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

_redis: aioredis.Redis | None = None

def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True
        )
    return _redis
FILE_EOF

cat << 'FILE_EOF' > infra/docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: mobil_postgres
    environment:
      POSTGRES_DB: mobil_db
      POSTGRES_USER: mobil_user
      POSTGRES_PASSWORD: mobil_password
    ports:
      - "5432:5432"
    networks:
      - mobil_net

  redis:
    image: redis:7-alpine
    container_name: mobil_redis
    ports:
      - "6379:6379"
    networks:
      - mobil_net

  api:
    build: .
    container_name: mobil_api
    command: uvicorn api.main_api:app --host 0.0.0.0 --port 8000
    environment:
      REDIS_HOST: redis
      DATABASE_URL: postgresql+asyncpg://mobil_user:mobil_password@postgres:5432/mobil_db
    depends_on:
      - redis
      - postgres
    ports:
      - "8000:8000"
    networks:
      - mobil_net

networks:
  mobil_net:
    driver: bridge
FILE_EOF

echo "✅ Estructura inicial creada correctamente."
