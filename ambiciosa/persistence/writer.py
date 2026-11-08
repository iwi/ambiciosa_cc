"""The DuckDB database: schema, strategy library, runs and bulk inserts.

DuckDB allows one writing process per file. Within that process, any number
of threads may share a `Database`: `Database.conn` gives each thread its own
cursor on the same database, so the web server's request threads and the
simulation runner's writer thread never share a connection.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from .. import __version__
from ..strategies import StrategySpec

SCHEMA_VERSION = 3
# Version history: 1 = Phase 1 schema; 2 = strategy_archive table (Phase 5);
# 3 = no primary keys on turn and throw (Phase 7).
DATA_TABLES = ("game", "game_player", "turn", "throw")


def schema_sql() -> str:
    return files("ambiciosa.persistence").joinpath("schema.sql").read_text(encoding="utf-8")


def _now() -> datetime:
    return datetime.now(UTC)


class StrategyConflict(ValueError):
    """A strategy version id is already stored with different content."""


class Database:
    def __init__(self, path: str | Path = ":memory:", *, read_only: bool = False) -> None:
        self.path = str(path)
        self.read_only = read_only
        self._root = duckdb.connect(self.path, read_only=read_only)
        self._owner = threading.get_ident()
        self._local = threading.local()
        if not read_only:
            self._apply_schema()

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """This thread's connection (the creating thread uses the root connection)."""
        if threading.get_ident() == self._owner:
            return self._root
        cur = getattr(self._local, "cursor", None)
        if cur is None:
            cur = self._local.cursor = self._root.cursor()
        return cur

    # ---------------------------------------------------------------- basics

    def _apply_schema(self) -> None:
        self.conn.execute(schema_sql())
        row = self.conn.execute("SELECT max(version) FROM schema_version").fetchone()
        current = row[0] if row else None
        if current is not None and current < 3:
            self._drop_detail_keys()
        if current is None or current < SCHEMA_VERSION:
            # schema.sql already created anything missing (every statement is idempotent).
            self.conn.execute("INSERT INTO schema_version VALUES (?, ?)", [SCHEMA_VERSION, _now()])
        elif current > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} uses schema version {current}; this software supports up to {SCHEMA_VERSION}"
            )

    def _drop_detail_keys(self) -> None:
        """Version 3 migration: rebuild turn and throw without their primary keys.

        DuckDB cannot drop a constraint in place, so each table is copied into a
        new one created from schema.sql's definition, then swapped in.
        """
        c = self.conn
        for table in ("turn", "throw"):
            keyed = c.execute(
                "SELECT count(*) FROM duckdb_constraints() WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
                [table]).fetchone()[0]
            if not keyed:
                continue
            ddl = schema_sql().split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]
            c.execute("BEGIN TRANSACTION")
            try:
                c.execute(f"CREATE TABLE {table}_v3 ({ddl})")
                c.execute(f"INSERT INTO {table}_v3 SELECT * FROM {table}")
                c.execute(f"DROP TABLE {table}")
                c.execute(f"ALTER TABLE {table}_v3 RENAME TO {table}")
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A new connection to the same database (the caller closes it)."""
        return self._root.cursor()

    def close(self) -> None:
        self._root.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.conn.execute(sql, params or [])
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    # ------------------------------------------------------- strategy library

    def get_strategy(self, strategy_version_id: uuid.UUID | str) -> StrategySpec:
        rows = self.query("SELECT * FROM strategy WHERE strategy_version_id = ?", [str(strategy_version_id)])
        if not rows:
            raise KeyError(f"no strategy version {strategy_version_id}")
        return self._spec_from_row(rows[0])

    def list_strategies(self, *, latest_only: bool = False, include_archived: bool = True) -> list[StrategySpec]:
        sql = "SELECT * FROM strategy"
        if not include_archived:
            sql += " WHERE strategy_id NOT IN (SELECT strategy_id FROM strategy_archive)"
        if latest_only:
            sql += " QUALIFY version = max(version) OVER (PARTITION BY strategy_id)"
        sql += " ORDER BY name, version"
        return [self._spec_from_row(r) for r in self.query(sql)]

    def strategy_versions(self, strategy_id: uuid.UUID | str) -> list[StrategySpec]:
        rows = self.query("SELECT * FROM strategy WHERE strategy_id = ? ORDER BY version", [str(strategy_id)])
        if not rows:
            raise KeyError(f"no strategy {strategy_id}")
        return [self._spec_from_row(r) for r in rows]

    def add_version(self, latest: StrategySpec, **changes: Any) -> StrategySpec:
        """Store an edit of a strategy as its next version (an edit that changes nothing returns `latest`)."""
        candidate = latest.new_version(**changes)
        if (candidate.name, candidate.description, candidate.params) == (
            latest.name, latest.description, latest.params
        ):
            return latest
        top = self.query("SELECT max(version) v FROM strategy WHERE strategy_id = ?", [str(latest.strategy_id)])
        data = candidate.model_dump()
        data["version"] = (top[0]["v"] or 0) + 1
        spec = StrategySpec.model_validate(data)
        self.conn.execute(
            "INSERT INTO strategy VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [str(spec.strategy_version_id), str(spec.strategy_id), spec.version, spec.name, spec.description,
             spec.type, json.dumps(spec.params, sort_keys=True), spec.created_at],
        )
        return spec

    def is_archived(self, strategy_id: uuid.UUID | str) -> bool:
        return bool(self.query("SELECT 1 FROM strategy_archive WHERE strategy_id = ?", [str(strategy_id)]))

    def archive_strategy(self, strategy_id: uuid.UUID | str) -> str:
        """Remove a strategy from the library.

        Versions that no stored game uses are deleted. If any version has
        results, every version is kept (results must keep pointing at the
        exact parameters) and the strategy is archived: hidden from the
        library but still shown in results. Returns "deleted" or "archived".
        """
        sid = str(strategy_id)
        self.strategy_versions(sid)  # KeyError if unknown
        used = self.query(
            "SELECT 1 FROM game_player WHERE strategy_version_id IN "
            "(SELECT strategy_version_id FROM strategy WHERE strategy_id = ?) LIMIT 1",
            [sid],
        )
        if used:
            self.conn.execute(
                "INSERT INTO strategy_archive VALUES (?, ?) ON CONFLICT DO NOTHING", [sid, _now()]
            )
            return "archived"
        self.conn.execute("DELETE FROM strategy WHERE strategy_id = ?", [sid])
        self.conn.execute("DELETE FROM strategy_archive WHERE strategy_id = ?", [sid])
        return "deleted"

    def restore_strategy(self, strategy_id: uuid.UUID | str) -> None:
        self.conn.execute("DELETE FROM strategy_archive WHERE strategy_id = ?", [str(strategy_id)])

    @staticmethod
    def _spec_from_row(row: dict[str, Any]) -> StrategySpec:
        return StrategySpec(
            strategy_version_id=row["strategy_version_id"],
            strategy_id=row["strategy_id"],
            version=row["version"],
            name=row["name"],
            description=row["description"] or "",
            type=str(row["type"]),
            params=json.loads(row["params"]),
            created_at=row["created_at"],
        )

    def resolve_strategy(self, spec: StrategySpec, conn: duckdb.DuckDBPyConnection | None = None) -> StrategySpec:
        """Store a strategy version if it is new and return the stored version.

        * A version id already stored is returned as stored (an error if its
          content differs: versions are immutable).
        * Otherwise, if the strategy (matched by strategy_id, else by name)
          already has a version with the same type and parameters, that
          version is reused, so the same YAML run twice does not multiply versions.
        * Otherwise a new version is stored: the next version number of the
          existing strategy, or version 1 of a new strategy.
        """
        c = conn or self.conn

        def fetch(sql: str, params: list[Any]) -> list[dict[str, Any]]:
            cur = c.execute(sql, params)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]

        same_id = fetch("SELECT * FROM strategy WHERE strategy_version_id = ?", [str(spec.strategy_version_id)])
        if same_id:
            stored = self._spec_from_row(same_id[0])
            if (stored.type, stored.params, stored.name) != (spec.type, spec.params, spec.name):
                raise StrategyConflict(
                    f"strategy version {spec.strategy_version_id} is stored with different content"
                )
            return stored

        family = fetch("SELECT * FROM strategy WHERE strategy_id = ? ORDER BY version", [str(spec.strategy_id)])
        if not family:
            family = fetch(
                "SELECT * FROM strategy WHERE strategy_id = "
                "(SELECT strategy_id FROM strategy WHERE name = ? ORDER BY created_at LIMIT 1) ORDER BY version",
                [spec.name],
            )
        for row in family:
            stored = self._spec_from_row(row)
            if stored.type == spec.type and stored.params == spec.params:
                return stored

        if family:
            data = spec.model_dump()
            data.update(strategy_id=family[0]["strategy_id"], version=family[-1]["version"] + 1)
            spec = StrategySpec.model_validate(data)
        c.execute(
            "INSERT INTO strategy VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                str(spec.strategy_version_id),
                str(spec.strategy_id),
                spec.version,
                spec.name,
                spec.description,
                spec.type,
                json.dumps(spec.params, sort_keys=True),
                spec.created_at,
            ],
        )
        return spec

    # ------------------------------------------------------------------ runs

    def create_simulation(
        self,
        simulation_id: uuid.UUID,
        *,
        name: str,
        master_seed: int,
        n_games_requested: int,
        record_level: str,
        config: dict[str, Any],
        source: str = "simulation",
        status: str = "running",
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        (conn or self.conn).execute(
            "INSERT INTO simulation (simulation_id, source, name, created_at, status, master_seed, "
            "n_games_requested, record_level, software_version, config) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                str(simulation_id),
                source,
                name,
                _now(),
                status,
                master_seed,
                n_games_requested,
                record_level,
                __version__,
                json.dumps(config),
            ],
        )

    def insert_batch(
        self,
        simulation_id: uuid.UUID,
        tables: dict[str, pa.Table],
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> int:
        """Append one batch of games atomically and count them as completed."""
        c = conn or self.conn
        n_games = tables["game"].num_rows
        c.execute("BEGIN TRANSACTION")
        try:
            for name in DATA_TABLES:
                tbl = tables.get(name)
                if tbl is None or tbl.num_rows == 0:
                    continue
                c.register("_batch", tbl)
                c.execute(f"INSERT INTO {name} BY NAME SELECT * FROM _batch")
                c.unregister("_batch")
            c.execute(
                "UPDATE simulation SET n_games_completed = n_games_completed + ? WHERE simulation_id = ?",
                [n_games, str(simulation_id)],
            )
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            try:
                c.unregister("_batch")
            except duckdb.Error:
                pass
            raise
        return n_games

    def set_status(
        self,
        simulation_id: uuid.UUID,
        status: str,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        finished = status in ("completed", "cancelled", "failed")
        (conn or self.conn).execute(
            "UPDATE simulation SET status = ?, finished_at = CASE WHEN ? THEN ? ELSE finished_at END "
            "WHERE simulation_id = ?",
            [status, finished, _now(), str(simulation_id)],
        )

    def mark_interrupted_runs(self) -> int:
        """Close runs left 'running' or 'pending' by a process that stopped.

        Simulations become 'failed'. Interactive games lived only in that
        process's memory and simply ended unfinished, so they become
        'cancelled'. Call this once when a writing process starts: DuckDB lets
        only one process write to the file, so no other process can still be
        running them. Returns the number of runs changed.
        """
        rows = self.query(
            "UPDATE simulation SET status = CASE WHEN source = 'interactive' THEN 'cancelled' ELSE 'failed' END, "
            "finished_at = ? WHERE status IN ('running', 'pending') RETURNING simulation_id",
            [_now()],
        )
        return len(rows)

    def get_simulation(self, simulation_id: uuid.UUID | str) -> dict[str, Any]:
        rows = self.query("SELECT * FROM simulation WHERE simulation_id = ?", [str(simulation_id)])
        if not rows:
            raise KeyError(f"no simulation {simulation_id}")
        row = rows[0]
        row["config"] = json.loads(row["config"])
        return row

    def list_simulations(self, source: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT simulation_id, source, name, created_at, finished_at, status, master_seed, "
            "n_games_requested, n_games_completed, record_level, software_version FROM simulation"
        )
        params: list[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        return self.query(sql + " ORDER BY created_at", params)

    def load_config(self, simulation_id: uuid.UUID | str):
        """The SimulationConfig of a stored run, with its strategy versions."""
        from ..simulation.config import SimulationConfig

        stored = self.get_simulation(simulation_id)["config"]
        specs = {
            str(p["strategy_version_id"]): self.get_strategy(p["strategy_version_id"])
            for p in stored["players"]
            if p.get("strategy_version_id")
        }
        return SimulationConfig.from_stored(stored, specs)

    def delete_simulation(self, simulation_id: uuid.UUID | str) -> None:
        """Remove a run and all of its games (strategy versions are kept).

        DuckDB checks foreign keys against committed data only, so the rows
        are deleted child tables first, each step committed on its own. If a
        step fails, the rows left behind still form a valid run that can be
        deleted again.
        """
        sid = str(simulation_id)
        games = "SELECT game_id FROM game WHERE simulation_id = ?"
        c = self.conn
        c.execute(f"DELETE FROM throw WHERE game_id IN ({games})", [sid])
        c.execute(f"DELETE FROM turn WHERE game_id IN ({games})", [sid])
        c.execute(f"DELETE FROM game_player WHERE game_id IN ({games})", [sid])
        c.execute("DELETE FROM game WHERE simulation_id = ?", [sid])
        c.execute("DELETE FROM simulation WHERE simulation_id = ?", [sid])
