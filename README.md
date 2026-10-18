# mobil-xml

Plataforma modular en Docker: API FastAPI (+ webhooks WhatsApp), orquestador de
tareas ADB sobre nodos Redroid, Ollama local, Redis (cola/estado), PostgreSQL y MongoDB.

## Arquitectura de red

| Red          | Servicios                                               | Notas                                   |
|--------------|---------------------------------------------------------|-----------------------------------------|
| `edge_net`   | api                                                     | Única con salida a Internet para la API |
| `data_net`   | redis, postgres, mongodb, api, orchestrator             | `internal: true` (sin Internet)         |
| `llm_net`    | ollama, orchestrator                                    |                                         |
| `device_net` | orchestrator, redroid-1, redroid-2                      | ADB solo aquí, nunca en el host         |

**Único puerto publicado:** API en `127.0.0.1:8000`. Para exponerla usa un proxy
inverso con TLS (Caddy/Nginx) en el host. DBs, Redis, Ollama y ADB no publican puertos
(`docker compose exec <servicio> ...` para administrarlos).

## Puesta en marcha

```bash
cd infra
./deploy.sh init      # crea .env con secretos aleatorios (permisos 600)
nano .env             # completa WHATSAPP_APP_SECRET / ACCESS_TOKEN / PHONE_NUMBER_ID
./deploy.sh up        # build + up + healthchecks + descarga del modelo Ollama
./deploy.sh status
./deploy.sh devices   # adb devices desde el orquestador
```

Requisitos del host para Redroid: módulos `binder_linux` (y `ashmem` según kernel).

## Cola de tareas

Las tareas se encolan con `RPUSH mobil:tasks '<json>'` (ver docstring de `core/orchestrator.py`).
Semántica *at-least-once*: reintentos con backoff que continúan desde la primera acción no
completada; agotados los intentos van a `mobil:tasks:dead`; tras una caída, las tareas en
`mobil:tasks:processing:<INSTANCE_ID>` se recuperan al arrancar. Una instancia por `INSTANCE_ID`.

## Pruebas

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements-dev.txt
pytest
```

## Identidades sintéticas (CLI)

```bash
pip install -r identity/requirements.txt
python -m identity.identity_manager -n 10 --seed 42
```
