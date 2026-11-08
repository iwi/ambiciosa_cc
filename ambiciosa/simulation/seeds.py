"""Per-game seeds (decision 9).

Each game's seed depends only on the master seed and the game index, never
on which worker plays it or in what order, so a run gives identical results
for any number of workers and any single game can be replayed on its own.

`SeedSequence(master, spawn_key=(i,))` is exactly the i-th child that
`SeedSequence(master).spawn(...)` would produce, but computed directly in
constant time.
"""

from __future__ import annotations

import secrets

import numpy as np

MAX_SEED = 2**64 - 1  # master_seed is stored as UBIGINT


def game_seed(master_seed: int, game_index: int) -> np.random.SeedSequence:
    if not 0 <= master_seed <= MAX_SEED:
        raise ValueError(f"master_seed must be between 0 and {MAX_SEED}")
    if game_index < 0:
        raise ValueError("game_index must be non-negative")
    return np.random.SeedSequence(master_seed, spawn_key=(game_index,))


def new_master_seed() -> int:
    """A fresh random master seed for runs where none is given."""
    return secrets.randbits(64)
