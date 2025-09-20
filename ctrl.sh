#!/usr/bin/env bash
set -euo pipefail
CMD=${1:-}
case "${CMD}" in
  build)
    docker compose build
    ;;
  up)
    docker compose up -d
    ;;
  down)
    docker compose down
    ;;
  rebuild)
    echo "This will DESTROY and rebuild the CMDB MCP service. Continue? [y/N] "
    read -r yn
    case "$yn" in
      y|Y|yes|YES) ;;
      *) exit 1;;
    esac
    docker compose down || true
    docker compose rm -f -v || true
    docker compose build --no-cache
    docker compose up -d
    ;;
  logs)
    docker compose logs -f
    ;;
  ps)
    docker compose ps
    ;;
  health)
    BASE="http://localhost:9001"
    AUTH=""
    if [[ "${REQUIRE_AUTH:-1}" != "0" ]]; then
      AUTH="-H Authorization: Bearer ${MCP_TOKEN:-secret123}"
    fi
    echo "[health] GET ${BASE}/health"
    curl -s ${AUTH} ${BASE}/health || true
    echo
    ;;
  *)
    echo "Usage: $0 {build|up|down|rebuild|logs|ps|health}" ; exit 1 ;;
esac
