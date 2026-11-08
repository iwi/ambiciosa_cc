"""Turn finished games into rows for the database (decision 7).

A `BatchRecorder` collects a chunk of games column by column and hands them
over as Arrow tables, one per database table, ready for a bulk insert.
What it keeps depends on the recording level:

    summary  game + game_player
    turns    + turn
    full     + throw

Game ids are derived from the simulation id and the game index, so the same
run always produces the same ids, whichever worker plays each game.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pyarrow as pa

from ..engine import Game, GameStatus

LEVELS = ("summary", "turns", "full")

_STATUS = {
    GameStatus.FINISHED: "finished",
    GameStatus.UNFINISHED: "unfinished",
    GameStatus.IN_PROGRESS: "abandoned",  # an interactive game saved before it ended
}

SCHEMAS: dict[str, pa.Schema] = {
    "game": pa.schema([
        ("game_id", pa.string()),
        ("simulation_id", pa.string()),
        ("game_index", pa.int32()),
        ("status", pa.string()),
        ("n_players", pa.uint8()),
        ("n_rounds", pa.int32()),
        ("duration_ms", pa.float64()),
    ]),
    "game_player": pa.schema([
        ("game_id", pa.string()),
        ("seat", pa.uint8()),
        ("play_order", pa.uint8()),
        ("player_type", pa.string()),
        ("display_name", pa.string()),
        ("strategy_version_id", pa.string()),
        ("final_score", pa.int32()),
        ("is_winner", pa.bool_()),
        ("turns_taken", pa.int32()),
        ("total_throws", pa.int32()),
        ("busts", pa.int32()),
    ]),
    "turn": pa.schema([
        ("game_id", pa.string()),
        ("seat", pa.uint8()),
        ("turn_number", pa.int32()),
        ("n_throws", pa.uint8()),
        ("end_reason", pa.string()),
        ("turn_score", pa.int32()),
        ("banked_after", pa.int32()),
    ]),
    "throw": pa.schema([
        ("game_id", pa.string()),
        ("seat", pa.uint8()),
        ("turn_number", pa.int32()),
        ("throw_number", pa.uint8()),
        ("die1", pa.uint8()),
        ("die2", pa.uint8()),
        ("die3", pa.uint8()),
        ("throw_score", pa.int16()),
        ("turn_points_after", pa.int32()),
        ("decision", pa.string()),
        ("reason", pa.string()),
    ]),
}

TABLES_FOR_LEVEL = {
    "summary": ("game", "game_player"),
    "turns": ("game", "game_player", "turn"),
    "full": ("game", "game_player", "turn", "throw"),
}


def game_id_for(simulation_id: uuid.UUID, game_index: int) -> uuid.UUID:
    return uuid.uuid5(simulation_id, str(game_index))


def needs_history(record_level: str) -> bool:
    return record_level != "summary"


class BatchRecorder:
    """Collects rows for a batch of games at one recording level."""

    def __init__(
        self,
        simulation_id: uuid.UUID,
        record_level: str,
        *,
        keep_reasons: bool = False,  # strategy explanations are stored for interactive games only
    ) -> None:
        if record_level not in LEVELS:
            raise ValueError(f"record_level must be one of {LEVELS}, got {record_level!r}")
        self.simulation_id = simulation_id
        self.sim_id_str = str(simulation_id)
        self.record_level = record_level
        self.keep_reasons = keep_reasons
        self.tables = TABLES_FOR_LEVEL[record_level]
        self._cols: dict[str, dict[str, list[Any]]] = {
            t: {name: [] for name in SCHEMAS[t].names} for t in self.tables
        }
        self.n_games = 0

    def add(self, game: Game, game_index: int, duration_ms: float | None = None) -> uuid.UUID:
        if needs_history(self.record_level) and not game.record_history:
            raise ValueError(f"record level {self.record_level!r} needs a game played with record_history=True")
        gid = game_id_for(self.simulation_id, game_index)
        g = str(gid)
        first_seat = game.play_order[0]
        winners = set(game.winners)

        c = self._cols["game"]
        c["game_id"].append(g)
        c["simulation_id"].append(self.sim_id_str)
        c["game_index"].append(game_index)
        c["status"].append(_STATUS[game.status])
        c["n_players"].append(game.config.n_players)
        c["n_rounds"].append(game.players[first_seat].turns_taken)
        c["duration_ms"].append(duration_ms)

        c = self._cols["game_player"]
        position = {seat: i for i, seat in enumerate(game.play_order)}
        for p in game.players:
            spec = p.config.strategy
            c["game_id"].append(g)
            c["seat"].append(p.seat)
            c["play_order"].append(position[p.seat])
            c["player_type"].append(p.config.player_type)
            c["display_name"].append(p.config.name)
            c["strategy_version_id"].append(None if spec is None else str(spec.strategy_version_id))
            c["final_score"].append(p.score)
            c["is_winner"].append(p.seat in winners)
            c["turns_taken"].append(p.turns_taken)
            c["total_throws"].append(p.total_throws)
            c["busts"].append(p.busts)

        if "turn" in self._cols:
            t = self._cols["turn"]
            th = self._cols.get("throw")
            for turn in game.history:
                t["game_id"].append(g)
                t["seat"].append(turn.seat)
                t["turn_number"].append(turn.turn_number)
                t["n_throws"].append(len(turn.throws))
                t["end_reason"].append(turn.end_reason.value)
                t["turn_score"].append(turn.turn_score)
                t["banked_after"].append(turn.banked_after)
                if th is None:
                    continue
                for r in turn.throws:
                    th["game_id"].append(g)
                    th["seat"].append(turn.seat)
                    th["turn_number"].append(turn.turn_number)
                    th["throw_number"].append(r.throw_number)
                    th["die1"].append(int(r.dice[0]))
                    th["die2"].append(int(r.dice[1]))
                    th["die3"].append(int(r.dice[2]))
                    th["throw_score"].append(r.score)
                    th["turn_points_after"].append(r.turn_points_after)
                    th["decision"].append(None if r.decision is None else r.decision.value)
                    th["reason"].append(r.reason if self.keep_reasons else None)

        self.n_games += 1
        return gid

    def to_arrow(self) -> dict[str, pa.Table]:
        """The collected rows, one Arrow table per database table."""
        return {
            t: pa.Table.from_pydict(cols, schema=SCHEMAS[t]) for t, cols in self._cols.items()
        }

    def rows(self, table: str) -> Iterator[tuple]:
        """Rows of one table as tuples (handy for tests and small inspections)."""
        cols = self._cols[table]
        return zip(*cols.values(), strict=True)
