"""POST /internal/poll-gmail — runs the incremental scan for every active Gmail user."""

import logging

from app.config_loader import ConfigError, load_config_and_users
from app.sources import gmail_ingestion

logger = logging.getLogger(__name__)


def run() -> None:
    try:
        config, users, _ = load_config_and_users()
    except ConfigError:
        logger.exception("gmail_poll_aborted_invalid_config")
        return
    gmail_ingestion.run_for_all_active_users(config, users)
