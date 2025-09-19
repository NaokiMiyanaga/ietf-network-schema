#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="docker compose -f "$ROOT_DIR"/docker-compose.yml"
SERVICE="cmdb-mcp"
PORT="${PORT:-9001}"

usage() {
  cat <<EOF
Usage: $0 <command>

Commands:
  up|start        Build (if needed) and start the CMDB MCP service
  down|stop       Stop and remove the service
  restart         Restart the service
  status          Show container status and port mapping
  logs [service]  Tail logs (default: cmdb)
  health          Check HTTP health (GET http://localhost:${PORT}/health)
  rebuild         Rebuild image (no cache) and start

Env:
  PORT            Host port for health check (default: 9001)
EOF
}

health() {
  echo "GET http://localhost:${PORT}/health"
  for i in {1..30}; do
    if curl -fsS "http://localhost:${PORT}/health" >/dev/null; then
      curl -s "http://localhost:${PORT}/health" | jq . || true
      return 0
    fi
    sleep 1
  done
  echo "Health check failed" >&2
  return 1
}

case "${1:-}" in
  up|start)
    ${COMPOSE} up -d
    ;;
  down|stop)
    ${COMPOSE} down
    ;;
  restart)
    ${COMPOSE} down || true
    ${COMPOSE} up -d
    ;;
  status)
    ${COMPOSE} ps
    ;;
  logs)
    svc="${2:-$SERVICE}"
    ${COMPOSE} logs -f "$svc"
    ;;
  health)
    health
    ;;
  rebuild)
    ${COMPOSE} down || true
    ${COMPOSE} build --no-cache
    ${COMPOSE} up -d
    ;;
  -h|--help|help|*)
    usage
    ;;
esac

