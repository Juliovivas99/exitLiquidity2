"""Environment configuration."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()


def get_discord_webhook_url() -> str:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise ValueError(
            "DISCORD_WEBHOOK_URL is missing or empty. Set it in .env (see README)."
        )
    return url


def get_log_level() -> int:
    name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, name, None)
    if isinstance(level, int):
        return level
    return logging.INFO


def get_poll_interval_seconds() -> int:
    raw = os.getenv("POLL_INTERVAL_SECONDS", "60").strip()
    try:
        n = int(raw)
    except ValueError:
        return 60
    return max(10, min(n, 300))


def get_outside_window_sleep_seconds() -> int:
    raw = os.getenv("OUTSIDE_WINDOW_SLEEP_SECONDS", "60").strip()
    try:
        n = int(raw)
    except ValueError:
        return 60
    return max(10, min(n, 3600))


def idle_on_non_trading_days() -> bool:
    """If true, sleep and re-check the calendar instead of exiting on holidays/weekends."""
    return os.getenv("HALT_BOT_IDLE_WHEN_CLOSED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def get_idle_sleep_seconds() -> int:
    """Sleep between NYSE calendar checks when HALT_BOT_IDLE_WHEN_CLOSED is enabled."""
    raw = os.getenv("HALT_BOT_IDLE_SLEEP_SECONDS", "3600").strip()
    try:
        n = int(raw)
    except ValueError:
        return 3600
    return max(60, min(n, 86400))
