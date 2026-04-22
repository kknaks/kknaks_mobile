#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

cmd="${1:-status}"

case "$cmd" in
  up)      docker compose up -d ;;
  down)    docker compose down ;;
  restart) docker compose restart redis ;;
  status)  docker compose ps ;;
  logs)    docker compose logs -f redis ;;
  cli)     docker exec -it kknaks-mobile-redis redis-cli ;;
  *)
    echo "Usage: $0 {up|down|restart|status|logs|cli}"
    exit 1
    ;;
esac
