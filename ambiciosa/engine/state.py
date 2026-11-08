"""Value types shared by the engine and strategies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"


class TurnEndReason(str, Enum):
    STOP = "stop"                      # player banked the turn total
    BUST_ZERO = "bust_zero"            # throw scored 0; turn scores 0
    BUST_NEGATIVE = "bust_negative"    # throw scored < 0; turn scores that value
    REACHED_TARGET = "reached_target"  # banked + turn total reached the target; auto-banked


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a strategy may look at when choosing CONTINUE or STOP (spec 4.1).

    Scores are banked (cumulative) scores, not counting the current turn.
    """

    turn_points: int               # accumulated in the current turn
    throws_this_turn: int
    last_throw_score: int
    my_score: int
    best_opponent_score: int | None  # None in single-player games
    gap_to_leader: int             # my_score - best_opponent_score; 0 in single-player
    points_to_target: int          # target - my_score
    num_opponents: int
    is_leading: bool               # strictly ahead of every opponent (True in single-player)
    turn_number: int               # this player's turn count, starting at 1
    target: int


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: Decision
    reason: str = ""
