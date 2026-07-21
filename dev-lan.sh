#!/usr/bin/env bash
# LAN debug launcher: backend in the myword-lan-backend Docker container
# (Python 3.12, since the host only has 3.8) + frontend via Vite.
#
# Usage:
#   ./dev-lan.sh             # start backend, then Vite in the foreground
#   ./dev-lan.sh backend     # start/refresh the backend container only
#   ./dev-lan.sh frontend    # start Vite only (assumes backend is up)
#
# Host :8000 is taken by the sibling "signtools" project, so the container
# publishes on 127.0.0.1:8001 and Vite proxies /api -> 8001.
# Data persists at MYWORD_DATA_DIR (default /tmp/myword-lan-data) — ephemeral.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="python:3.12-slim"
CONTAINER="myword-lan-backend"
HOST_PORT="${MYWORD_HOST_PORT:-8001}"
CONTAINER_PORT=8000
DATA_DIR="${MYWORD_DATA_DIR:-/tmp/myword-lan-data}"
PIP_CACHE="${MYWORD_PIP_CACHE:-/tmp/myword-pip-cache}"
PEPPER="${MYWORD_API_TOKEN_PEPPER:-lan-test-pepper-at-least-16-bytes}"

log() { printf '[dev-lan] %s\n' "$*"; }

lan_ip() {
  # First 10.x / 192.168.x address, skipping loopback and docker bridges (172.16/12).
  # Each pipe ends in `|| true` so pipefail/SIGPIPE from `head` can't abort the script.
  local addrs="${MYWORD_LAN_IP:-$(hostname -I 2>/dev/null || true)}"
  local ip
  ip="$(printf '%s\n' "$addrs" | tr ' ' '\n' | grep -E '^(10\.|192\.168\.)' | grep -vE '^127\.' | head -n1 || true)"
  if [[ -n "$ip" ]]; then
    printf '%s\n' "$ip"
    return
  fi
  ip="$(printf '%s\n' "$addrs" | tr ' ' '\n' | grep -vE '^(127\.|172\.)' | head -n1 || true)"
  printf '%s\n' "$ip"
}

container_env() {  # $1 = VAR
  docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | grep -E "^$1=" | head -1 | cut -d= -f2-
}

ensure_backend() {
  local ip="$1"
  local want_url="http://${ip}:5173"
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    local have_url
    have_url="$(container_env PUBLIC_BASE_URL || true)"
    if [[ "$have_url" != "$want_url" ]]; then
      log "LAN IP changed ('$have_url' -> '$want_url'); recreating container"
      docker rm -f "$CONTAINER" >/dev/null
    elif docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      log "backend container already running (ip=$ip)"
      return 0
    else
      log "starting existing backend container"
      docker start "$CONTAINER" >/dev/null
      return 0
    fi
  fi

  mkdir -p "$DATA_DIR" "$PIP_CACHE"
  log "creating backend container (127.0.0.1:${HOST_PORT} -> :${CONTAINER_PORT}, ip=$ip)"
  docker run -d --name "$CONTAINER" -w /workspace/backend \
    -p "127.0.0.1:${HOST_PORT}:${CONTAINER_PORT}" \
    -v "$REPO:/workspace" \
    -v "$PIP_CACHE:/root/.cache/pip" \
    -v "$DATA_DIR:/data" \
    -e DATABASE_URL=sqlite:////data/vocab.db \
    -e "API_TOKEN_PEPPER=${PEPPER}" \
    -e "TRUSTED_HOSTS=127.0.0.1,localhost,${ip}" \
    -e "PUBLIC_BASE_URL=${want_url}" \
    -e "CORS_ORIGINS=${want_url}" \
    -e TRUSTED_PROXY_CIDRS=172.16.0.0/12 \
    "$IMAGE" \
    sh -lc 'pip install -e . && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000' >/dev/null
}

wait_health() {
  log "waiting for backend health (up to 120s)…"
  local i
  for ((i = 1; i <= 120; i++)); do
    if docker exec "$CONTAINER" python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${CONTAINER_PORT}/healthz/ready',timeout=2).status==200 else 1)" \
      >/dev/null 2>&1; then
      log "backend healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  log "backend not healthy after 120s; last logs:" >&2
  docker logs --tail 40 "$CONTAINER" >&2 || true
  return 1
}

start_frontend() {
  local ip="$1"
  log "starting Vite on http://${ip}:5173 (proxy -> 127.0.0.1:${HOST_PORT})"
  log "open http://${ip}:5173 from any LAN device"
  cd "$REPO/frontend"
  export VITE_API_TARGET="http://127.0.0.1:${HOST_PORT}"
  export VITE_PROXY_USER="${MYWORD_PROXY_USER:-lan-dev}"
  exec npm run dev
}

main() {
  local cmd="${1:-all}"
  local ip
  ip="$(lan_ip)"
  if [[ -z "$ip" ]]; then
    log "could not detect a LAN IP" >&2
    exit 1
  fi
  log "LAN IP = $ip"

  case "$cmd" in
    backend)
      ensure_backend "$ip"
      wait_health
      log "done; frontend: ./dev-lan.sh frontend (or ./dev-lan.sh for both)"
      ;;
    frontend)
      start_frontend "$ip"
      ;;
    all)
      ensure_backend "$ip"
      wait_health
      start_frontend "$ip"
      ;;
    *)
      log "usage: $0 [backend|frontend|all]" >&2
      exit 2
      ;;
  esac
}

main "$@"
