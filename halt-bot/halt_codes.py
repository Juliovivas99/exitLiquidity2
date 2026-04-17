"""NASDAQ halt reason codes — labels, descriptions, and Discord emoji."""

from __future__ import annotations

from typing import TypedDict


class HaltCodeInfo(TypedDict):
    label: str
    description: str
    emoji: str


HALT_CODE_INFO: dict[str, HaltCodeInfo] = {
    "LUDP": {
        "label": "Circuit Breaker",
        "description": "Limit Up/Limit Down volatility pause (5 min)",
        "emoji": "⚡",
    },
    "T1": {
        "label": "News Pending",
        "description": "Halt pending release of material news",
        "emoji": "📰",
    },
    "T12": {
        "label": "Volatility Halt",
        "description": "Unusual price movement under investigation",
        "emoji": "🔍",
    },
    "H10": {
        "label": "SEC Suspension",
        "description": "SEC has suspended trading, possible manipulation",
        "emoji": "🚨",
    },
    "M": {
        "label": "Market-Wide Halt",
        "description": "Market-wide circuit breaker triggered",
        "emoji": "🛑",
    },
    "IPO1": {
        "label": "IPO Halt",
        "description": "IPO not yet open for trading",
        "emoji": "🚀",
    },
    "T5": {
        "label": "Resume",
        "description": "Single stock trading resumption",
        "emoji": "✅",
    },
    "MWCB": {
        "label": "Market-Wide Resume",
        "description": "Market-wide circuit breaker lifted",
        "emoji": "✅",
    },
}

DEFAULT_HALT_INFO: HaltCodeInfo = {
    "label": "Trading Halt",
    "description": "See NASDAQ reason code for details.",
    "emoji": "⏸️",
}


def get_halt_info(halt_code: str | None) -> HaltCodeInfo:
    if not halt_code:
        return DEFAULT_HALT_INFO
    return HALT_CODE_INFO.get(halt_code.upper(), DEFAULT_HALT_INFO)
