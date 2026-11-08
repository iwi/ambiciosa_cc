"""Ready-made example strategies, one or more per type.

Their ids are fixed (derived from the name) so they stay the same across
installations and database resets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from .spec import StrategySpec

_NAMESPACE = uuid.UUID("6b1f3a9e-2c4d-4e8f-9a1b-0c2d3e4f5a6b")
_CREATED = datetime(2026, 11, 7, tzinfo=UTC)


def _preset(name: str, type: str, params: dict, description: str) -> StrategySpec:
    sid = uuid.uuid5(_NAMESPACE, name)
    return StrategySpec(
        strategy_id=sid,
        strategy_version_id=uuid.uuid5(sid, "v1"),
        name=name,
        type=type,
        params=params,
        description=description,
        created_at=_CREATED,
    )


PRESETS: tuple[StrategySpec, ...] = (
    _preset("Stop at 30", "threshold", {"threshold": 30}, "Bank as soon as the turn reaches 30 points."),
    _preset("Stop at 50", "threshold", {"threshold": 50}, "Bank as soon as the turn reaches 50 points."),
    _preset("Three throws", "max_throws", {"max_throws": 3}, "Throw up to three times, then bank."),
    _preset(
        "50 points or 4 throws",
        "combined",
        {"threshold": 50, "max_throws": 4, "logic": "or"},
        "Bank at 50 points or after the fourth throw, whichever comes first.",
    ),
    _preset("Coin flip 75%", "random", {"p_continue": 0.75}, "Continue three times in four."),
    _preset(
        "Safe ahead, bold behind",
        "game_state",
        {"leading_threshold": 30, "trailing_threshold": 60, "close_to_win_points": 100, "close_threshold": None},
        "Bank at 30 when ahead, 60 when behind or tied, and go for the win when 100 or fewer points are needed.",
    ),
)
