#!/usr/bin/env python3
"""
Manual checks for halt-bot (works outside the 9:25–4:05 ET polling window).

  python test_halt_bot.py                    # RSS fetch + parse + resumption heuristics
  python test_halt_bot.py --discord          # POST two synthetic TEST embeds
  python test_halt_bot.py --discord-live     # POST one+ embed(s) built from current RSS rows
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Any

import pytz

from feed import HALT_FEED_URL, fetch_halts, is_resumption

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test_halt_bot")

ET = pytz.timezone("America/New_York")


def _halt_json_safe(h: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in h.items():
        if isinstance(v, datetime):
            out[k] = v.astimezone(ET).isoformat()
        else:
            out[k] = v
    return out


def fetch_and_validate() -> tuple[list[dict[str, Any]] | None, int]:
    logger.info("Feed URL: %s", HALT_FEED_URL)
    halts = fetch_halts()
    if not halts:
        logger.error("fetch_halts() returned no rows (network, parse error, or empty feed).")
        return None, 1

    logger.info("Parsed %s halt row(s).", len(halts))
    sample = halts[0]
    logger.info("Sample row:\n%s", json.dumps(_halt_json_safe(sample), indent=2))

    resume_ct = sum(1 for h in halts if h.get("is_resumption"))
    ludp_ct = sum(1 for h in halts if (h.get("halt_code") or "").upper() == "LUDP")
    logger.info("Rows with is_resumption=True: %s", resume_ct)
    logger.info("Rows with halt_code=LUDP: %s", ludp_ct)

    for h in halts[:5]:
        if (h.get("halt_code") or "").upper() == "LUDP":
            if is_resumption(h):
                logger.error("BUG: LUDP row should not be is_resumption: %s", h.get("symbol"))
                return None, 1
            break
    else:
        logger.warning("No LUDP in first 5 rows; skipped LUDP vs resumption check.")

    return halts, 0


def run_discord_tests() -> int:
    try:
        from config import get_discord_webhook_url
        from discord_bot import send_halt_alert

        get_discord_webhook_url()
    except ValueError as e:
        logger.error("%s", e)
        return 1

    now = datetime.now(ET)
    halt_time = now
    resume_time = now

    new_halt = {
        "halt_id": "test-halt-bot-new",
        "symbol": "TEST",
        "name": "Halt Bot Self-Test (NEW)",
        "halt_time": halt_time,
        "resume_time": None,
        "halt_code": "T1",
        "market": "NASDAQ",
        "pause_price": None,
    }
    resumption = {
        "halt_id": "test-halt-bot-resume",
        "symbol": "TEST",
        "name": "Halt Bot Self-Test (RESUME)",
        "halt_time": halt_time,
        "resume_time": resume_time,
        "halt_code": "T5",
        "market": "NASDAQ",
        "pause_price": None,
    }

    logger.info("Posting sample NEW HALT embed…")
    send_halt_alert(new_halt, False)
    logger.info("Posting sample RESUMPTION embed…")
    send_halt_alert(resumption, True)
    logger.info("Done. Check your Discord channel for two test messages.")
    return 0


def run_discord_live_from_feed(halts: list[dict[str, Any]]) -> int:
    """Post embed(s) using real symbols from the latest RSS snapshot (not a new market event)."""
    try:
        from config import get_discord_webhook_url
        from discord_bot import send_halt_alert

        get_discord_webhook_url()
    except ValueError as e:
        logger.error("%s", e)
        return 1

    if halts:
        row = dict(halts[0])
        logger.info(
            "Posting LIVE RSS row (new-halt embed): %s — %s",
            row.get("symbol"),
            row.get("halt_code"),
        )
        send_halt_alert(row, False)
    else:
        logger.warning("No rows in feed; skipped halt embed.")

    res = next((h for h in halts if h.get("resume_time")), None)
    if res:
        row = dict(res)
        logger.info(
            "Posting LIVE RSS row (resumption embed): %s — %s",
            row.get("symbol"),
            row.get("halt_code"),
        )
        send_halt_alert(row, True)
    else:
        logger.info("No rows with resume_time in current feed; skipped resumption embed.")

    logger.info(
        "Done. These are current feed snapshots, not necessarily new halts since you last ran main.py."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Test halt-bot RSS + optional Discord webhook.")
    p.add_argument(
        "--discord",
        action="store_true",
        help="Send two synthetic TEST embeds (requires DISCORD_WEBHOOK_URL in .env)",
    )
    p.add_argument(
        "--discord-live",
        action="store_true",
        help="Send embed(s) built from the latest real RSS rows (requires .env webhook)",
    )
    args = p.parse_args()

    halts, code = fetch_and_validate()
    if code != 0 or halts is None:
        return code

    if args.discord:
        code = run_discord_tests()
        if code != 0:
            return code
    if args.discord_live:
        code = run_discord_live_from_feed(halts)
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    sys.exit(main())
