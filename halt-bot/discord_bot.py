"""Discord webhook client — embeds for halts and resumptions."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import pytz
import requests

from config import get_discord_webhook_url
from halt_codes import get_halt_info

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

_SEVERE = frozenset({"LUDP", "T12", "H10", "M"})
_NEWS_OR_IPO = frozenset({"T1", "IPO1"})


def _fmt_et(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = ET.localize(dt)
    else:
        dt = dt.astimezone(ET)
    return dt.strftime("%Y-%m-%d %I:%M:%S %p %Z")


def _embed_color_new_halt(halt_code: str) -> int:
    c = halt_code.upper()
    if c in _SEVERE:
        return 0xFF0000
    if c in _NEWS_OR_IPO:
        return 0xFF8C00
    return 0x808080


def send_halt_alert(halt: dict[str, Any]) -> None:
    """Post a Discord embed for a new halt or a resumption."""
    webhook = get_discord_webhook_url()
    if halt.get("is_resumption"):
        embed = _build_resumption_embed(halt)
    else:
        embed = _build_new_halt_embed(halt)

    payload = {"embeds": [embed]}
    _post_webhook(webhook, payload)


def _build_new_halt_embed(halt: dict[str, Any]) -> dict[str, Any]:
    code = halt.get("halt_code") or "UNKNOWN"
    info = get_halt_info(code)
    emoji = info["emoji"]
    label = info["label"]
    desc = info["description"]
    symbol = halt.get("symbol") or "?"
    color = _embed_color_new_halt(code)

    fields: list[dict[str, Any]] = [
        {"name": "Company", "value": str(halt.get("name") or "—"), "inline": False},
        {"name": "Exchange", "value": str(halt.get("market") or "—"), "inline": False},
        {"name": "Halt Time", "value": _fmt_et(halt.get("halt_time")), "inline": False},
        {
            "name": "Reason",
            "value": f"{code} — {desc}",
            "inline": False,
        },
    ]
    pause = halt.get("pause_price")
    if pause:
        fields.append({"name": "Pause Price", "value": str(pause), "inline": False})

    resume_eta = halt.get("resume_time")
    fields.append(
        {
            "name": "Resume ETA",
            "value": _fmt_et(resume_eta) if resume_eta else "TBD",
            "inline": False,
        }
    )

    return {
        "title": f"{emoji} {label} — {symbol}",
        "color": color,
        "fields": fields,
        "footer": {"text": "NASDAQ Trader | Halt Monitor"},
    }


def _build_resumption_embed(halt: dict[str, Any]) -> dict[str, Any]:
    symbol = halt.get("symbol") or "?"
    return {
        "title": f"✅ Trading Resumed — {symbol}",
        "color": 0x00B300,
        "fields": [
            {"name": "Company", "value": str(halt.get("name") or "—"), "inline": False},
            {"name": "Exchange", "value": str(halt.get("market") or "—"), "inline": False},
            {"name": "Resumed At", "value": _fmt_et(halt.get("resume_time")), "inline": False},
            {"name": "Originally Halted", "value": _fmt_et(halt.get("halt_time")), "inline": False},
        ],
        "footer": {"text": "NASDAQ Trader | Halt Monitor"},
    }


def _post_webhook(webhook: str, payload: dict[str, Any]) -> None:
    try:
        r = requests.post(webhook, json=payload, timeout=20)
        # Discord often returns 204 No Content on success, not 200.
        if 200 <= r.status_code < 300:
            return
        logger.error("Discord webhook returned %s: %s", r.status_code, r.text[:500])
    except Exception:
        logger.exception("Discord webhook request failed")

    time.sleep(3)
    try:
        r2 = requests.post(webhook, json=payload, timeout=20)
        if not (200 <= r2.status_code < 300):
            logger.error(
                "Discord webhook retry failed (%s): %s",
                r2.status_code,
                r2.text[:500],
            )
    except Exception:
        logger.exception("Discord webhook retry raised")
