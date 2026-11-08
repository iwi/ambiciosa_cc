"""Simulation engine: seeds, configuration, recording and the parallel runner."""

from .config import FULL_RECORD_LIMIT, SeatConfig, SimulationConfig, find_preset
from .recorder import LEVELS, BatchRecorder, game_id_for
from .runner import Progress, SimulationRunner, chunk_bounds, play_chunk, replay_game
from .seeds import game_seed, new_master_seed

__all__ = [
    "FULL_RECORD_LIMIT",
    "LEVELS",
    "BatchRecorder",
    "Progress",
    "SeatConfig",
    "SimulationConfig",
    "SimulationRunner",
    "chunk_bounds",
    "find_preset",
    "game_id_for",
    "game_seed",
    "new_master_seed",
    "play_chunk",
    "replay_game",
]
