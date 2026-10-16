#!/usr/bin/env bash
# ============================================================
# mobil-xml / infra - Script de despliegue
# Uso: ./deploy.sh [up|down|restart|status|logs|pull-model|reset]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ACTION="${1:-up}"

log()  { echo -e "\033[1;34m[infra]\033[0m $*"; }
warn() { echo -e "\033[1;33m[aviso]\033[0m $*"; }
fail() { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

check_requirements() {
  command -v docker >/dev/null 2>&1 || fail "Docker no esta instalado."
  docker info >/dev/null 2>&1 || fail "El daemon de Docker no responde (revisa permisos o si esta iniciado)."
  docker compose version >/dev/null 2>&1 || fail "Falta el plugin 'docker compose' (v2)."
}

check_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    warn "No existia .env; se creo desde .env.example."
    fail "Edita infra/.env, cambia los valores change_me_* y vuelve a ejecutar."
  fi
  if grep -q "change_me_" .env; then
    fail "Aun hay valores 'change_me_*' en .env. Cambialos antes de desplegar."
  fi
}

check_redroid_kernel() {
  if [ ! -e /dev/binderfs ] && ! lsmod 2>/dev/null | grep -q binder_linux; then
    warn "No se detecta binder_linux en el kernel. Redroid probablemente no arrancara."
    warn "Carga los modulos en el host:  sudo modprobe binder_linux devices=\"binder,hwbinder,vndbinder\""
  fi
}

load_env() {
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
}

pull_model() {
  load_env
  if [ -z "${OLLAMA_MODEL:-}" ]; then
    log "OLLAMA_MODEL vacio; se omite la descarga del modelo."
    return 0
  fi
  log "Descargando modelo Ollama: ${OLLAMA_MODEL} (puede tardar)..."
  docker compose exec -T ollama ollama pull "${OLLAMA_MODEL}"
}

wait_healthy() {
  log "Esperando a que los servicios queden saludables..."
  local services=(postgres redis mongodb ollama)
  local tries=60
  for svc in "${services[@]}"; do
    local cid status
    cid="$(docker compose ps -q "$svc")"
    [ -n "$cid" ] || fail "El servicio $svc no se creo."
    for ((i = 1; i <= tries; i++)); do
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
      [ "$status" = "healthy" ] && { log "  $svc: OK"; break; }
      [ "$i" -eq "$tries" ] && fail "$svc no llego a estado healthy."
      sleep 5
    done
  done
}

case "$ACTION" in
  up)
    check_requirements
    check_env
    check_redroid_kernel
    log "Descargando imagenes..."
    docker compose pull
    log "Levantando contenedores..."
    docker compose up -d
    wait_healthy
    pull_model
    log "Infraestructura lista:"
    docker compose ps
    ;;
  down)
    check_requirements
    log "Deteniendo contenedores (los volumenes se conservan)..."
    docker compose down
    ;;
  restart)
    check_requirements
    check_env
    docker compose down
    docker compose up -d
    wait_healthy
    ;;
  status)
    check_requirements
    docker compose ps
    ;;
  logs)
    check_requirements
    docker compose logs -f --tail=100 "${2:-}"
    ;;
  pull-model)
    check_requirements
    check_env
    pull_model
    ;;
  reset)
    check_requirements
    warn "Esto BORRA todos los volumenes (bases de datos, modelos, datos de Android)."
    read -r -p "Escribe 'SI' para confirmar: " confirm
    [ "$confirm" = "SI" ] || fail "Cancelado."
    docker compose down -v
    ;;
  *)
    echo "Uso: $0 [up|down|restart|status|logs [servicio]|pull-model|reset]"
    exit 1
    ;;
esac
