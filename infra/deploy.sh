#!/usr/bin/env bash
# ============================================================
# mobil-xml / infra - Script de despliegue
# Uso: ./deploy.sh [init|up|down|restart|status|logs [servicio]|devices|pull-model|reset]
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

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Lee VAR de .env SIN ejecutarlo como shell (evita inyeccion / caracteres especiales).
env_get() {
  local line
  line="$(grep -E "^$1=" .env | tail -n1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line#\"}"; line="${line%\"}"
  line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

init_env() {
  [ -f .env.example ] || fail "No existe .env.example"
  if [ -f .env ]; then
    fail ".env ya existe; no se sobrescribe. Borralo manualmente si quieres regenerarlo."
  fi
  umask 077
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" == *change_me_* ]]; then
      line="$(printf '%s' "$line" | sed "s/change_me_[a-z_]*/$(rand_hex)/")"
    fi
    printf '%s\n' "$line"
  done < .env.example > .env
  chmod 600 .env
  log ".env creado con secretos aleatorios (permisos 600)."
  warn "Completa a mano WHATSAPP_APP_SECRET, WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID."
}

check_env() {
  if [ ! -f .env ]; then
    fail "No existe infra/.env. Ejecuta primero:  ./deploy.sh init"
  fi
  if grep -q "change_me_" .env; then
    fail "Aun hay valores 'change_me_*' en .env. Cambialos (o regenera con ./deploy.sh init)."
  fi
  chmod 600 .env 2>/dev/null || true

  local var val
  for var in POSTGRES_PASSWORD REDIS_PASSWORD MONGO_ROOT_PASSWORD; do
    val="$(env_get "$var")"
    [[ "$val" =~ ^[A-Za-z0-9_-]{16,}$ ]] \
      || fail "$var debe tener 16+ caracteres y solo [A-Za-z0-9_-] (sin \$, comillas ni espacios)."
  done
  val="$(env_get API_KEY)"
  [[ "$val" =~ ^[A-Za-z0-9_-]{32,}$ ]] \
    || fail "API_KEY debe tener 32+ caracteres y solo [A-Za-z0-9_-]."
  for var in POSTGRES_USER POSTGRES_DB MONGO_ROOT_USER; do
    [ -n "$(env_get "$var")" ] || fail "Falta $var en .env"
  done

  val="$(env_get API_BIND)"
  if [ -n "$val" ] && [ "$val" != "127.0.0.1" ] && [ "$val" != "localhost" ]; then
    warn "API_BIND=$val publica la API fuera del host. Recomendado: 127.0.0.1 + proxy inverso con TLS."
  fi
  for var in WHATSAPP_APP_SECRET WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID; do
    [ -n "$(env_get "$var")" ] || warn "$var vacio: las funciones de WhatsApp responderan 503/403 hasta configurarlo."
  done
}

check_redroid_kernel() {
  if [ ! -e /dev/binderfs ] && ! lsmod 2>/dev/null | grep -q binder_linux; then
    warn "No se detecta binder_linux en el kernel. Redroid probablemente no arrancara."
    warn "Carga los modulos en el host:  sudo modprobe binder_linux devices=\"binder,hwbinder,vndbinder\""
  fi
}

pull_model() {
  local model
  model="$(env_get OLLAMA_MODEL)"
  if [ -z "$model" ]; then
    log "OLLAMA_MODEL vacio; se omite la descarga del modelo."
    return 0
  fi
  log "Descargando modelo Ollama: ${model} (puede tardar)..."
  docker compose exec -T ollama ollama pull "$model"
}

# wait_service <servicio> <intentos> <fatal:1|0>
wait_service() {
  local svc="$1" tries="$2" fatal="$3" cid status i
  cid="$(docker compose ps -q "$svc")"
  if [ -z "$cid" ]; then
    [ "$fatal" = "1" ] && fail "El servicio $svc no se creo."
    warn "El servicio $svc no se creo."; return 0
  fi
  for ((i = 1; i <= tries; i++)); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    if [ "$status" = "healthy" ]; then log "  $svc: OK"; return 0; fi
    sleep 5
  done
  if [ "$fatal" = "1" ]; then
    docker compose logs --tail=50 "$svc" || true
    fail "$svc no llego a estado healthy."
  fi
  warn "$svc aun no esta healthy (puede estar arrancando)."
}

wait_healthy() {
  log "Esperando a que los servicios queden saludables..."
  local svc
  for svc in postgres redis mongodb ollama api orchestrator; do
    wait_service "$svc" 60 1
  done
  # Android tarda en arrancar y depende del kernel del host: no es fatal.
  for svc in redroid-1 redroid-2; do
    wait_service "$svc" 36 0
  done
}

case "$ACTION" in
  init)
    init_env
    ;;
  up)
    check_requirements
    check_env
    check_redroid_kernel
    log "Construyendo imagenes de aplicacion..."
    docker compose build --pull
    log "Descargando imagenes base..."
    docker compose pull --ignore-buildable || warn "No se pudieron actualizar todas las imagenes (se usaran las locales)."
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
    log_args=(logs -f --tail=100)
    if [ -n "${2:-}" ]; then
      log_args+=("$2")
    fi
    docker compose "${log_args[@]}"
    ;;
  devices)
    check_requirements
    docker compose exec -T orchestrator adb devices
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
    docker compose down -v --remove-orphans
    ;;
  *)
    echo "Uso: $0 [init|up|down|restart|status|logs [servicio]|devices|pull-model|reset]"
    exit 1
    ;;
esac
