#!/usr/bin/env python3
"""NASDAQ trade halt monitor — polls RSS and posts Discord webhook alerts."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, time as dtime

import pandas_market_calendars as mcal
import pytz
import schedule

from config import (
    get_discord_webhook_url,
    get_idle_sleep_seconds,
    get_log_level,
    get_outside_window_sleep_seconds,
    get_poll_interval_seconds,
    idle_on_non_trading_days,
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


def _bootstrap_seen_ids(seen: set[str]) -> None:
    halts = fetch_halts()
    for h in halts:
        hid = h.get("halt_id")
        if hid:
            seen.add(str(hid))
    logger.info("Startup sync: tracking %s existing halt id(s) (no alerts sent).", len(seen))


def _poll_cycle(seen_halt_ids: set[str]) -> None:
    halts = fetch_halts()
    now = _now_et()
    stamp = now.strftime("%H:%M:%S %Z")
    for halt in halts:
        hid = halt.get("halt_id")
        if not hid:
            continue
        sid = str(hid)
        if sid in seen_halt_ids:
            continue
        seen_halt_ids.add(sid)
        try:
            send_halt_alert(halt)
        except Exception:
            logger.exception("send_halt_alert failed for %s", sid)
        sym = halt.get("symbol", "?")
        code = halt.get("halt_code", "?")
        if halt.get("is_resumption"):
            logger.info("[%s] RESUMPTION: %s — %s", stamp, sym, code)
        else:
            logger.info("[%s] NEW HALT: %s — %s", stamp, sym, code)


def main() -> None:
    try:
        get_discord_webhook_url()
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)

    while not _is_trading_day_today():
        if idle_on_non_trading_days():
            sec = get_idle_sleep_seconds()
            logger.info(
                "No trading today (NYSE calendar); sleeping %ss (HALT_BOT_IDLE_WHEN_CLOSED).",
                sec,
            )
            end = time.monotonic() + sec
            while time.monotonic() < end:
                if _shutdown:
                    logger.info("Shutdown requested during idle wait.")
                    sys.exit(0)
                time.sleep(min(5.0, end - time.monotonic()))
            continue
        logger.info("No trading today (NYSE calendar). Exiting.")
        sys.exit(0)

    _log_today_session_times()

    seen_halt_ids: set[str] = set()
    _bootstrap_seen_ids(seen_halt_ids)

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
                schedule.every(poll_sec).seconds.do(_poll_cycle, seen_halt_ids)
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
