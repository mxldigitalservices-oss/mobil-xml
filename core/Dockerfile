FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends adb \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/app --uid 10001 app

WORKDIR /app

COPY core/requirements.txt core/requirements.txt
RUN pip install -r core/requirements.txt

COPY core/ core/

USER app
CMD ["python", "-m", "core.orchestrator"]
