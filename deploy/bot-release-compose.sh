#!/bin/sh
set -eu
release_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "${1:-}" in config|build|up|ps|logs|stop|start|exec|images) ;; *) echo "Only explicit bot release operations are allowed; no down." >&2; exit 1;; esac
test -f "${PLANNER_BOT_ENV_FILE:?Existing bot env path required}"
test -f "$release_root/deploy/planner.env"
exec docker compose --project-directory "$release_root" --env-file "$PLANNER_BOT_ENV_FILE" --env-file "$release_root/deploy/planner.env" -p bitrix-missed-calls-bot -f "$release_root/compose.bot.release.yaml" "$@"
