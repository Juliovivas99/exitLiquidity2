"""NASDAQ Trader trade halt RSS — fetch and parse."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

import feedparser
import pytz

logger = logging.getLogger(__name__)

HALT_FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"

ET = pytz.timezone("America/New_York")

# RSS reason codes that represent an actual resumption (not LULD expected resume ETA).
RESUMPTION_CODES = frozenset({"T5", "MWCB"})

_REQUEST_HEADERS = {
    "User-Agent": "halt-bot/1.0 (+https://github.com/)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_et_datetime(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str or not time_str:
        return None
    date_str = date_str.strip()
    time_str = time_str.strip()
    m_date = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if not m_date:
        logger.warning("Unrecognized halt date format: %s", date_str)
        return None
    month, day, year = map(int, m_date.groups())
    m_time = re.match(
        r"(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?", time_str
    )
    if not m_time:
        logger.warning("Unrecognized halt time format: %s", time_str)
        return None
    hh, mm, ss = int(m_time.group(1)), int(m_time.group(2)), int(m_time.group(3))
    micro = 0
    if m_time.group(4):
        frac = m_time.group(4)[:6].ljust(6, "0")
        micro = int(frac)
    try:
        naive = datetime(year, month, day, hh, mm, ss, micro)
    except ValueError:
        logger.warning("Invalid halt datetime: %s %s", date_str, time_str)
        return None
    return ET.localize(naive)


def _fallback_halt_id(parts: list[str]) -> str:
    raw = "|".join(parts)
    return "syn|" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def is_resumption(halt: dict[str, Any]) -> bool:
    """True when the feed row is a trading resumption (not an LULD ETA row)."""
    if halt.get("resume_time") is None:
        return False
    code = (halt.get("halt_code") or "").upper()
    return code in RESUMPTION_CODES


def _parse_entry(entry: Any) -> dict[str, Any] | None:
    try:
        symbol = _clean_str(getattr(entry, "ndaq_issuesymbol", None) or entry.get("ndaq_issuesymbol"))
        halt_date = _clean_str(getattr(entry, "ndaq_haltdate", None) or entry.get("ndaq_haltdate"))
        halt_time_raw = _clean_str(getattr(entry, "ndaq_halttime", None) or entry.get("ndaq_halttime"))
        name = _clean_str(getattr(entry, "ndaq_issuename", None) or entry.get("ndaq_issuename"))
        market = _clean_str(getattr(entry, "ndaq_market", None) or entry.get("ndaq_market"))
        halt_code = _clean_str(getattr(entry, "ndaq_reasoncode", None) or entry.get("ndaq_reasoncode"))
        pause_raw = _clean_str(getattr(entry, "ndaq_pausethresholdprice", None) or entry.get("ndaq_pausethresholdprice"))
        res_date = _clean_str(
            getattr(entry, "ndaq_resumptiondate", None) or entry.get("ndaq_resumptiondate")
        )
        res_trade = _clean_str(
            getattr(entry, "ndaq_resumptiontradetime", None) or entry.get("ndaq_resumptiontradetime")
        )

        if not symbol or not halt_date or not halt_time_raw:
            logger.warning("Skipping RSS entry: missing symbol, halt date, or halt time")
            return None

        halt_time = _parse_et_datetime(halt_date, halt_time_raw)
        if halt_time is None:
            return None

        resume_time: datetime | None = None
        if res_date and res_trade:
            resume_time = _parse_et_datetime(res_date, res_trade)

        pause_price: str | None = pause_raw

        halt_id = _clean_str(entry.get("id"))
        if not halt_id:
            halt_id = _fallback_halt_id(
                [symbol, halt_date, halt_time_raw, halt_code or "", res_date or "", res_trade or ""]
            )

        row: dict[str, Any] = {
            "halt_id": halt_id,
            "symbol": symbol,
            "name": name or "—",
            "halt_time": halt_time,
            "resume_time": resume_time,
            "halt_code": halt_code or "UNKNOWN",
            "market": market or "—",
            "pause_price": pause_price,
        }
        row["is_resumption"] = is_resumption(row)
        return row
    except Exception:
        logger.exception("Malformed RSS entry skipped")
        return None


def fetch_halts() -> list[dict[str, Any]]:
    """Fetch the NASDAQ halt RSS and return parsed halt dicts."""
    try:
        parsed = feedparser.parse(HALT_FEED_URL, request_headers=_REQUEST_HEADERS)
    except Exception:
        logger.exception("Failed to fetch or parse halt RSS")
        return []

    if getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None):
        logger.warning("RSS parse warning: %s", parsed.bozo_exception)

    out: list[dict[str, Any]] = []
    for entry in getattr(parsed, "entries", []) or []:
        row = _parse_entry(entry)
        if row is not None:
            out.append(row)
    return out
