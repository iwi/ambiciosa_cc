"""Export runs to Parquet or CSV, one file per table, for R and other tools."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from .writer import Database

FORMATS = ("parquet", "csv")

# table -> SELECT returning that table's rows for the chosen runs ($ids is a list of UUIDs)
_SELECTS = {
    "simulation": "SELECT * FROM simulation WHERE simulation_id IN (SELECT unnest($ids))",
    "strategy": (
        "SELECT * FROM strategy WHERE strategy_version_id IN ("
        " SELECT gp.strategy_version_id FROM game_player gp JOIN game g USING (game_id)"
        " WHERE g.simulation_id IN (SELECT unnest($ids)))"
    ),
    "game": "SELECT * FROM game WHERE simulation_id IN (SELECT unnest($ids))",
}
for _t in ("game_player", "turn", "throw"):
    _SELECTS[_t] = (
        f"SELECT x.* FROM {_t} x JOIN game g USING (game_id) WHERE g.simulation_id IN (SELECT unnest($ids))"
    )

EXPORT_TABLES = ("simulation", "strategy", "game", "game_player", "turn", "throw")


def export_simulations(
    db: Database,
    simulation_ids: Sequence[uuid.UUID | str],
    out_dir: str | Path,
    fmt: str = "parquet",
    *,
    include_empty: bool = False,
) -> list[Path]:
    """Write each table's rows for the given runs to `out_dir/<table>.<fmt>`.

    Tables with no rows (for example `throw` for a summary-level run) are
    skipped unless `include_empty` is set. Returns the files written.
    """
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {fmt!r}")
    ids = [str(uuid.UUID(str(s))) for s in simulation_ids]
    if not ids:
        raise ValueError("choose at least one simulation to export")
    known = {str(r["simulation_id"]) for r in db.query("SELECT simulation_id FROM simulation")}
    missing = [i for i in ids if i not in known]
    if missing:
        raise KeyError(f"no simulation {', '.join(missing)}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    options = "FORMAT parquet, COMPRESSION zstd" if fmt == "parquet" else "FORMAT csv, HEADER true"
    # COPY takes no parameters; the ids are inlined, which is safe because each
    # one has been parsed as a UUID above.
    id_list = "[" + ", ".join(f"'{i}'" for i in ids) + "]::UUID[]"
    for table in EXPORT_TABLES:
        select = _SELECTS[table].replace("$ids", id_list)
        if not include_empty:
            if db.conn.execute(f"SELECT EXISTS ({select})").fetchone()[0] is False:
                continue
        path = out / f"{table}.{fmt}"
        target = str(path).replace("'", "''")
        db.conn.execute(f"COPY ({select}) TO '{target}' ({options})")
        written.append(path)
    return written
