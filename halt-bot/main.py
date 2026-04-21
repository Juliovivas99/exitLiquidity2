#!/usr/bin/env python3
"""NASDAQ trade halt monitor — polls RSS and posts Discord webhook alerts."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, time as dtime
from typing import Any

import pandas_market_calendars as mcal
import pytz
import schedule

from config import (
    get_discord_webhook_url,
    get_log_level,
    get_outside_window_sleep_seconds,
    get_poll_interval_seconds,
)
from discord_bot import send_halt_alert
from feed import fetch_halts


def _configure_logging() -> None:
    logging.basicConfig(
        level=get_log_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


_configure_logging()
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

SESSION_START = dtime(9, 25)
SESSION_END = dtime(16, 5)

_shutdown = False


def _event_key(halt: dict[str, Any]) -> str | None:
    """
    Build a stable identifier for a halt "event".

    NASDAQ's RSS `entry.id` can change as fields (like resumption/ETA) update, which
    causes duplicate "new halt" alerts if we dedupe on `halt_id`. Instead, we key
    on the immutable parts: symbol + halt_time (+ market).
    """
    sym = halt.get("symbol")
    ht = halt.get("halt_time")
    if not sym or not isinstance(ht, datetime):
        return None
    # Normalize to ET for consistent string keys.
    ht_et = ht.astimezone(ET) if ht.tzinfo else ET.localize(ht)
    market = halt.get("market") or ""
    return f"{sym}|{market}|{ht_et.isoformat(timespec='seconds')}"


def _handle_shutdown(signum: int, frame: object | None) -> None:
    global _shutdown
    _shutdown = True
    logger.info("Received signal %s; shutting down after current iteration.", signum)


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


def _now_et() -> datetime:
    return datetime.now(ET)


def _is_trading_day_today() -> bool:
    today = _now_et().date()
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=today, end_date=today)
    return not sched.empty


def _log_today_session_times() -> None:
    today = _now_et().date()
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=today, end_date=today)
    if sched.empty:
        return
    row = sched.iloc[0]
    open_utc = row["market_open"]
    close_utc = row["market_close"]
    open_et = open_utc.tz_convert("America/New_York")
    close_et = close_utc.tz_convert("America/New_York")
    logger.info(
        "NYSE session today: %s – %s ET",
        open_et.strftime("%I:%M %p %Z"),
        close_et.strftime("%I:%M %p %Z"),
    )


def _in_trading_window(now_et: datetime) -> bool:
    tt = now_et.time()
    return SESSION_START <= tt <= SESSION_END


def _bootstrap_seen_ids(seen: dict[str, dict[str, Any]]) -> None:
    halts = fetch_halts()
    for h in halts:
        ek = _event_key(h)
        if ek:
            seen[ek] = h
    logger.info(
        "Startup: pre-loaded %s existing halts (by event key). Monitoring for new halts and resume updates...",
        len(seen),
    )


def _poll_cycle(seen_halts: dict[str, dict[str, Any]]) -> None:
    halts = fetch_halts()
    now = _now_et()
    today = now.date()
    stamp = now.strftime("%H:%M:%S %Z")
    for halt in halts:
        halt_time = halt.get("halt_time")
        sym = halt.get("symbol", "?")
        if not isinstance(halt_time, datetime):
            logger.debug("[SKIP] Stale halt from %s: %s", "UNKNOWN", sym)
            continue
        halt_date_et = halt_time.astimezone(ET).date() if halt_time.tzinfo else halt_time.date()
        if halt_date_et != today:
            logger.debug("[SKIP] Stale halt from %s: %s", halt_date_et, sym)
            continue

        ek = _event_key(halt)
        if not ek:
            continue

        if ek not in seen_halts:
            seen_halts[ek] = halt
            try:
                send_halt_alert(halt, is_resumption=False)
            except Exception:
                logger.exception("send_halt_alert failed for %s", ek)
            code = halt.get("halt_code", "?")
            logger.info("[%s] NEW HALT: %s — %s", stamp, sym, code)
            continue

        prev = seen_halts[ek]
        prev_is_resumption = bool(prev.get("is_resumption"))
        curr_is_resumption = bool(halt.get("is_resumption"))
        if (not prev_is_resumption) and curr_is_resumption:
            seen_halts[ek] = halt
            try:
                send_halt_alert(halt, is_resumption=True)
            except Exception:
                logger.exception("send_halt_alert failed for resumption %s", ek)
            was_code = prev.get("halt_code", "?")
            logger.info("[%s] RESUMED: %s — was %s", stamp, sym, was_code)
        else:
            seen_halts[ek] = halt


def main() -> None:
    try:
        get_discord_webhook_url()
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)

    if not _is_trading_day_today():
        print("Market closed today (weekend/holiday). Exiting.")
        sys.exit(0)

    _log_today_session_times()

    seen_halts: dict[str, dict[str, Any]] = {}
    _bootstrap_seen_ids(seen_halts)

    poll_sec = get_poll_interval_seconds()
    outside_sec = get_outside_window_sleep_seconds()
    inside_window = False

    logger.info(
        "Halt monitor running (poll=%ss in window, outside_window_sleep=%ss).",
        poll_sec,
        outside_sec,
    )

    while not _shutdown:
        try:
            now_et = _now_et()
            in_w = _in_trading_window(now_et)

            if in_w and not inside_window:
                schedule.clear()
                schedule.every(poll_sec).seconds.do(_poll_cycle, seen_halts)
                inside_window = True
                logger.info("Entered polling window (%s–%s ET).", SESSION_START, SESSION_END)

            if not in_w and inside_window:
                inside_window = False
                schedule.clear()
                logger.info("Left polling window; sleeping until next session.")

            if in_w:
                schedule.run_pending()
                time.sleep(1)
            else:
                end = time.monotonic() + outside_sec
                while time.monotonic() < end:
                    if _shutdown:
                        break
                    time.sleep(min(1.0, end - time.monotonic()))
        except Exception:
            logger.exception("Polling loop error (continuing)")

    logger.info("Shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
