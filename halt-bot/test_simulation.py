#!/usr/bin/env python3
"""Self-contained halt lifecycle simulation (no RSS, no Discord)."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, Callable

_BOT_DIR = Path(__file__).resolve().parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

import pytz

import main as halt_main
from feed import is_resumption

ET = pytz.timezone("America/New_York")


def _resume_default_et(days_offset: int = 0) -> datetime:
    base = halt_main._now_et().date() + timedelta(days=days_offset)
    return ET.localize(datetime.combine(base, dtime(10, 35)))


def make_halt(
    symbol: str = "TEST",
    halt_code: str = "LUDP",
    resume_time: datetime | None = None,
    days_offset: int = 0,
) -> dict[str, Any]:
    """Fake halt row aligned with feed.parse shape.

    - halt_id: ``test|{symbol}-{halt_code}``
    - halt_time: date is today in ET plus ``days_offset`` (0 = today, -1 = yesterday) at 10:30 AM ET
    - resume_time: ``None`` in the dict if ``resume_time`` is omitted; otherwise the given
      datetime (naive values are localized to ET). For a default 10:35 AM ET resume on that
      halt date, use ``resume_time=_resume_default_et(days_offset)``.
    """
    halt_id = f"test|{symbol}-{halt_code}"
    base_date = halt_main._now_et().date() + timedelta(days=days_offset)
    halt_ts = ET.localize(datetime.combine(base_date, dtime(10, 30)))
    if resume_time is None:
        rt = None
    else:
        rt = resume_time if resume_time.tzinfo else ET.localize(resume_time)

    row: dict[str, Any] = {
        "halt_id": halt_id,
        "symbol": symbol,
        "name": "Test Co",
        "halt_time": halt_ts,
        "resume_time": rt,
        "halt_code": halt_code,
        "market": "NASDAQ",
        "pause_price": None,
    }
    row["is_resumption"] = is_resumption(row)
    return row


def _make_fetch_sequence(sequences: list[list[dict[str, Any]]]) -> Callable[[], list[dict[str, Any]]]:
    idx = 0

    def fake_fetch() -> list[dict[str, Any]]:
        nonlocal idx
        out = sequences[idx]
        idx += 1
        return out

    return fake_fetch


def _patch_alerts() -> tuple[list[tuple[dict[str, Any], bool]], Callable[..., None]]:
    calls: list[tuple[dict[str, Any], bool]] = []

    def capture(halt: dict[str, Any], is_resumption: bool = False) -> None:
        calls.append((halt, is_resumption))

    return calls, capture


def scenario_1_new_halt_dedup() -> None:
    h1 = make_halt()
    calls, capture = _patch_alerts()
    fetch_fn = _make_fetch_sequence([[], [h1], [h1]])
    halt_main.fetch_halts = fetch_fn  # type: ignore[method-assign]
    halt_main.send_halt_alert = capture  # type: ignore[method-assign]
    seen: dict[str, dict[str, Any]] = {}
    halt_main._bootstrap_seen_ids(seen)
    halt_main._poll_cycle(seen)
    halt_main._poll_cycle(seen)
    assert len(calls) == 1, f"Expected 1 alert call, got {len(calls)}"
    assert calls[0][1] is False, "First alert should be is_resumption=False"


def scenario_2_resumption() -> None:
    h_new = make_halt()
    h_resume = make_halt(resume_time=_resume_default_et())
    calls, capture = _patch_alerts()
    halt_main.fetch_halts = _make_fetch_sequence([[], [h_new], [h_resume]])  # type: ignore[method-assign]
    halt_main.send_halt_alert = capture  # type: ignore[method-assign]
    seen: dict[str, dict[str, Any]] = {}
    halt_main._bootstrap_seen_ids(seen)
    halt_main._poll_cycle(seen)
    halt_main._poll_cycle(seen)
    assert len(calls) == 2, f"Expected 2 alert calls, got {len(calls)}"
    assert calls[0][1] is False
    assert calls[1][1] is True


def scenario_3_stale_date() -> None:
    stale = make_halt(days_offset=-1)
    log_msgs: list[str] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_msgs.append(record.getMessage())

    h = CaptureHandler()
    h.setLevel(logging.DEBUG)
    lg = logging.getLogger("main")
    old_level = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        calls, capture = _patch_alerts()
        halt_main.fetch_halts = _make_fetch_sequence([[], [stale]])  # type: ignore[method-assign]
        halt_main.send_halt_alert = capture  # type: ignore[method-assign]
        seen: dict[str, dict[str, Any]] = {}
        halt_main._bootstrap_seen_ids(seen)
        halt_main._poll_cycle(seen)
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_level)

    assert len(calls) == 0, f"Expected no alerts, got {len(calls)}"
    assert any("[SKIP] Stale halt" in m for m in log_msgs), (
        f"Expected '[SKIP] Stale halt' in logs, got: {log_msgs!r}"
    )


def scenario_4_bootstrap_suppression() -> None:
    h = make_halt()
    calls, capture = _patch_alerts()
    halt_main.fetch_halts = _make_fetch_sequence([[h], [h]])  # type: ignore[method-assign]
    halt_main.send_halt_alert = capture  # type: ignore[method-assign]
    seen: dict[str, dict[str, Any]] = {}
    halt_main._bootstrap_seen_ids(seen)
    halt_main._poll_cycle(seen)
    assert len(calls) == 0, f"Expected no alerts, got {len(calls)}"


def scenario_5_bootstrap_existing_resume() -> None:
    h = make_halt(resume_time=_resume_default_et())
    calls, capture = _patch_alerts()
    halt_main.fetch_halts = _make_fetch_sequence([[h], [h]])  # type: ignore[method-assign]
    halt_main.send_halt_alert = capture  # type: ignore[method-assign]
    seen: dict[str, dict[str, Any]] = {}
    halt_main._bootstrap_seen_ids(seen)
    halt_main._poll_cycle(seen)
    assert len(calls) == 0, f"Expected no alerts, got {len(calls)}"


def _restore_main_patches() -> None:
    import feed as feed_mod
    import discord_bot as discord_mod

    halt_main.fetch_halts = feed_mod.fetch_halts  # type: ignore[method-assign]
    halt_main.send_halt_alert = discord_mod.send_halt_alert  # type: ignore[method-assign]


_main_logger_snap: dict[str, Any] = {}


def _quiet_main_logger() -> None:
    """Stop ``main`` logs from propagating to the root handler (no RSS/Discord I/O)."""
    m = logging.getLogger("main")
    _main_logger_snap.clear()
    _main_logger_snap["propagate"] = m.propagate
    _main_logger_snap["level"] = m.level
    _main_logger_snap["handlers"] = list(m.handlers)
    m.handlers.clear()
    m.propagate = False
    m.setLevel(logging.WARNING)


def _restore_main_logger() -> None:
    if not _main_logger_snap:
        return
    m = logging.getLogger("main")
    for h in m.handlers[:]:
        m.removeHandler(h)
    for h in _main_logger_snap["handlers"]:
        m.addHandler(h)
    m.propagate = _main_logger_snap["propagate"]
    m.setLevel(_main_logger_snap["level"])
    _main_logger_snap.clear()


def main() -> None:
    _quiet_main_logger()

    scenarios: list[tuple[str, Callable[[], None]]] = [
        ("Scenario 1: New halt detected", scenario_1_new_halt_dedup),
        ("Scenario 2: Resumption detected", scenario_2_resumption),
        ("Scenario 3: Stale date filtered", scenario_3_stale_date),
        ("Scenario 4: Bootstrap suppression", scenario_4_bootstrap_suppression),
        ("Scenario 5: Bootstrap with existing resumption", scenario_5_bootstrap_existing_resume),
    ]
    failed = False
    try:
        for label, fn in scenarios:
            try:
                fn()
                print(f"✅ PASS — {label}")
            except AssertionError as e:
                failed = True
                print(f"❌ FAIL — {label}: {e}")
    finally:
        _restore_main_patches()
        _restore_main_logger()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
