"""Game engine: dice, scoring, turns and games.

This package has no I/O and no dependency on strategies, simulation,
persistence, the API or the frontend.
"""

from .dice import DiceSource, Face, RandomDice, ScriptedDice, Throw, normalise_weights
from .game import (
    EndRule,
    Game,
    GameConfig,
    GameStatus,
    IllegalAction,
    PlayerConfig,
    PlayerState,
    ThrowRecord,
    TurnRecord,
)
from .scoring import DEFAULT_SCORING, SCORE_TABLE, Scoring, score_throw
from .state import Decision, DecisionContext, DecisionResult, TurnEndReason

__all__ = [
    "DEFAULT_SCORING",
    "Decision",
    "DecisionContext",
    "DecisionResult",
    "DiceSource",
    "EndRule",
    "Face",
    "Game",
    "GameConfig",
    "GameStatus",
    "IllegalAction",
    "PlayerConfig",
    "PlayerState",
    "RandomDice",
    "SCORE_TABLE",
    "ScriptedDice",
    "Scoring",
    "Throw",
    "ThrowRecord",
    "TurnEndReason",
    "TurnRecord",
    "normalise_weights",
    "score_throw",
]
