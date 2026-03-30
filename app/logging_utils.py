import logging
import os


def configure_logging() -> None:
    level_name = os.getenv('LOG_LEVEL', 'INFO').strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level)


def payload_logging_enabled() -> bool:
    return os.getenv('LOG_PAYLOADS', '').strip().lower() == 'true'
