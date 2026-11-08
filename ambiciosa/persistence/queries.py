"""Read-side queries used by the command line now and the API in Phase 5."""

from __future__ import annotations

import uuid
from typing import Any

from .writer import Database


def strategy_summary(db: Database, simulation_id: uuid.UUID | str) -> list[dict[str, Any]]:
    """Headline numbers per seat for one run (from v_strategy_summary)."""
    return db.query(
        "SELECT * EXCLUDE (simulation_id, source, simulation_name) FROM v_strategy_summary "
        "WHERE simulation_id = ? ORDER BY seat",
        [str(simulation_id)],
    )


def run_overview(db: Database, simulation_id: uuid.UUID | str) -> dict[str, Any]:
    """Game-level counts for one run: finished, unfinished, shared wins, mean length."""
    rows = db.query(
        """
        SELECT count(*)                                         AS games,
               count(*) FILTER (WHERE status = 'finished')      AS finished,
               count(*) FILTER (WHERE status = 'unfinished')    AS unfinished,
               avg(n_rounds)                                    AS mean_rounds,
               (SELECT count(*) FROM (
                   SELECT game_id FROM game_player JOIN game USING (game_id)
                   WHERE simulation_id = ? AND is_winner
                   GROUP BY game_id HAVING count(*) > 1))        AS shared_wins
        FROM game WHERE simulation_id = ?
        """,
        [str(simulation_id), str(simulation_id)],
    )
    return rows[0]


def game_by_index(db: Database, simulation_id: uuid.UUID | str, game_index: int) -> dict[str, Any]:
    rows = db.query(
        "SELECT * FROM game WHERE simulation_id = ? AND game_index = ?", [str(simulation_id), game_index]
    )
    if not rows:
        raise KeyError(f"no game {game_index} in simulation {simulation_id}")
    return rows[0]


def game_history(db: Database, game_id: uuid.UUID | str) -> dict[str, Any]:
    """Players, turns and throws of one game, in playing order (whatever was recorded)."""
    gid = str(game_id)
    players = db.query("SELECT * FROM game_player WHERE game_id = ? ORDER BY seat", [gid])
    turns = db.query(
        """
        SELECT t.* FROM turn t JOIN game_player gp USING (game_id, seat)
        WHERE game_id = ? ORDER BY t.turn_number, gp.play_order
        """,
        [gid],
    )
    throws = db.query(
        "SELECT * FROM throw WHERE game_id = ? ORDER BY turn_number, seat, throw_number", [gid]
    )
    by_turn: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for th in throws:
        by_turn.setdefault((th["seat"], th["turn_number"]), []).append(th)
    for t in turns:
        t["throws"] = by_turn.get((t["seat"], t["turn_number"]), [])
    return {"players": players, "turns": turns}
