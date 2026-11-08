"""Strategy engine: strategy types, stored specs, presets and automated play."""

# Registration order = display order = spec 4.2 numbering.
from . import threshold  # noqa: F401  isort: skip
from . import max_throws  # noqa: F401  isort: skip
from . import combined  # noqa: F401  isort: skip
from . import random_choice  # noqa: F401  isort: skip
from . import game_state  # noqa: F401  isort: skip
from .base import Params, Strategy, StrategyType, get_type, list_types, register
from .combined import CombinedParams, CombinedStrategy
from .game_state import GameStateParams, GameStateStrategy
from .max_throws import MaxThrowsParams, MaxThrowsStrategy
from .play import AutomatedPlayers, play_automated
from .presets import PRESETS
from .random_choice import RandomParams, RandomStrategy
from .spec import StrategySpec
from .threshold import ThresholdParams, ThresholdStrategy

__all__ = [
    "PRESETS",
    "AutomatedPlayers",
    "CombinedParams",
    "CombinedStrategy",
    "GameStateParams",
    "GameStateStrategy",
    "MaxThrowsParams",
    "MaxThrowsStrategy",
    "Params",
    "RandomParams",
    "RandomStrategy",
    "Strategy",
    "StrategySpec",
    "StrategyType",
    "ThresholdParams",
    "ThresholdStrategy",
    "get_type",
    "list_types",
    "play_automated",
    "register",
]
