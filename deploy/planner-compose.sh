#!/bin/sh
# Exact Mini App project only. Never infer the main bot's compose.yaml.
set -eu
planner_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "${1:-}" in
    config|build|up|ps|logs|stop|start|exec|run|images|version) ;;
    *) echo "Укажите команду Mini App: config/build/up/ps/logs/stop/start/exec/run/images/version. down не используется." >&2; exit 1 ;;
esac
if [ ! -f "$planner_root/deploy/planner.env" ]; then
    echo "Создайте deploy/planner.env по проверенным настройкам VPS." >&2
    exit 1
fi
if [ ! -f "${PLANNER_BOT_ENV_FILE:-}" ]; then
    echo "Укажите PLANNER_BOT_ENV_FILE: абсолютный путь к существующему .env бота." >&2
    exit 1
fi
exec docker compose --project-directory "$planner_root" \
    --env-file "$PLANNER_BOT_ENV_FILE" --env-file "$planner_root/deploy/planner.env" \
    -p bitrix-workday-planner -f "$planner_root/compose.planner.yaml" "$@"
