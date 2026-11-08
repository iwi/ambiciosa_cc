"""Shared helpers for the simulation and persistence tests."""

import pytest

from ambiciosa.simulation import SimulationConfig

# Columns that legitimately differ between two runs of the same games.
VOLATILE = {"duration_ms"}


def canonical_rows(db, simulation_id):
    """Every stored row of a run with game ids replaced by game indices.

    Two runs of the same games (different simulation ids, so different game
    ids) give equal results exactly when their canonical rows are equal.
    """
    sid = str(simulation_id)
    out = {}
    for table in ("game", "game_player", "turn", "throw"):
        cols = [c for (c,) in db.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall() if c not in VOLATILE | {"game_id", "simulation_id"}]
        select = ", ".join(f"x.{c}" for c in cols if c != "game_index")
        if table == "game":
            sql = f"SELECT x.game_index, {select} FROM game x WHERE simulation_id = ? ORDER BY 1"
        else:
            sql = (f"SELECT g.game_index, {select} FROM {table} x JOIN game g USING (game_id) "
                   f"WHERE g.simulation_id = ? ORDER BY ALL")
        out[table] = db.conn.execute(sql, [sid]).fetchall()
    return out


@pytest.fixture
def canonical():
    return canonical_rows


def quick_config(**overrides):
    """A small, fast run: short games, three different strategies (one random)."""
    data = dict(
        name="quick",
        n_games=60,
        master_seed=20261107,
        target=200,
        workers=1,
        players=["Stop at 30", "Coin flip 75%", {"name": "Bold", "strategy": {"type": "threshold", "params": {"threshold": 60}}}],
    )
    data.update(overrides)
    return SimulationConfig.model_validate(data)


@pytest.fixture
def make_config():
    return quick_config
