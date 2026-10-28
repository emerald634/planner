import logging
import signal
import time
from datetime import UTC, datetime, timedelta

from app.core.config import settings, warn_if_insecure_defaults
from app.core.crm_policy import require_legacy_export
from app.db.session import SessionLocal
from app.integrations.bitrix24 import Bitrix24Gateway
from app.services.bitrix_sync import BitrixSyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
warn_if_insecure_defaults(settings)
running = True


def stop(*_args) -> None:
    global running
    running = False


def run() -> None:
    require_legacy_export()
    if not settings.bitrix24_webhook_url:
        logger.warning("BITRIX24_WEBHOOK_URL is empty; worker is waiting for configuration")
    next_source_sync = datetime.min.replace(tzinfo=UTC)
    while running:
        if settings.bitrix24_webhook_url:
            gateway = Bitrix24Gateway(settings.bitrix24_webhook_url)
            with SessionLocal() as db:
                service = BitrixSyncService(db, gateway)
                try:
                    now = datetime.now(UTC)
                    if now >= next_source_sync:
                        service.sync_sources()
                        next_source_sync = now + timedelta(
                            seconds=settings.bitrix_source_sync_interval_seconds
                        )
                    service.create_pending_leads()
                    service.monitor_entities()
                except Exception:
                    db.rollback()
                    logger.exception("Bitrix worker iteration failed")
        time.sleep(max(5, settings.bitrix_entity_poll_interval_seconds))


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    run()
