"""Rotating file + console logging. Call once per process."""
from __future__ import annotations

import logging
import logging.handlers

from config.settings import get_settings

_configured = False


def setup_logging(process_name: str) -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / f"{process_name}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.addHandler(file_handler)
    root.addHandler(console)
    for noisy in ("urllib3", "apscheduler.executors.default", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
