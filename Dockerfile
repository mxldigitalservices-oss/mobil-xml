FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --no-create-home --uid 10001 app
WORKDIR /app

COPY api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt

COPY api/ api/

USER app
EXPOSE 8000
CMD ["uvicorn", "api.main_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
