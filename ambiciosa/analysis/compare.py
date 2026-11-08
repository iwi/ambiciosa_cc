"""Comparing runs, and strategies across runs.

A strategy's win rate depends on its opponents, so strategies are never
pooled across runs: the strategy view is a matrix of strategy × run, with
each cell that strategy's result in that run.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from ..persistence import Database, run_overview
from .stats import player_metrics, wilson


def compare_runs(db: Database, simulation_ids: Sequence[uuid.UUID | str]) -> dict[str, Any]:
    runs = []
    for raw in simulation_ids:
        sid = str(uuid.UUID(str(raw)))
        sim = db.get_simulation(sid)
        target = int(sim["config"].get("target", 1000))
        runs.append({
            "simulation": {
                "simulation_id": sid, "name": sim["name"], "source": str(sim["source"]),
                "status": str(sim["status"]), "n_games_completed": sim["n_games_completed"],
                "record_level": str(sim["record_level"]), "master_seed": sim["master_seed"],
                "created_at": sim["created_at"], "target": target,
                "end_rule": sim["config"].get("end_rule", "first_to_target"),
                "n_players": len(sim["config"].get("players", [])),
            },
            "overview": run_overview(db, sid),
            "players": player_metrics(db, sid, target),
        })

    matrix: dict[str, dict[str, Any]] = {}
    for run in runs:
        sid = run["simulation"]["simulation_id"]
        for p in run["players"]:
            key = str(p["strategy_version_id"]) if p["strategy_version_id"] else f"human:{p['display_name']}"
            row = matrix.setdefault(key, {
                "strategy_version_id": str(p["strategy_version_id"]) if p["strategy_version_id"] else None,
                "strategy_name": p["strategy_name"] or p["display_name"],
                "strategy_version": p["strategy_version"],
                "strategy_type": p["strategy_type"],
                "cells": {},
            })
            # A strategy may sit in several seats of one run: combine them within that run.
            cell = row["cells"].setdefault(sid, {"games": 0, "wins": 0.0, "turns": 0, "points": 0.0, "seats": [],
                                                 "reached_target": 0, "_turns_reached": 0.0})
            cell["reached_target"] += p["reached_target"]
            cell["_turns_reached"] += (p["turns_to_target_mean"] or 0) * p["reached_target"]
            cell["games"] += p["games"]
            cell["wins"] += p["wins"]
            cell["turns"] += p["turns"]
            cell["points"] += (p["points_per_turn"] or 0) * p["turns"]
            cell["seats"].append(p["seat"])
    strategies = []
    for row in matrix.values():
        for cell in row["cells"].values():
            cell["win_rate"] = cell["wins"] / cell["games"] if cell["games"] else None
            ci = wilson(cell["wins"], cell["games"])
            cell["win_rate_low"], cell["win_rate_high"] = ci if ci else (None, None)
            cell["points_per_turn"] = cell["points"] / cell["turns"] if cell["turns"] else None
            cell["turns_to_target_mean"] = (
                cell["_turns_reached"] / cell["reached_target"] if cell["reached_target"] else None
            )
            del cell["points"], cell["_turns_reached"]
        strategies.append(row)
    strategies.sort(key=lambda r: (r["strategy_name"] or "", r["strategy_version"] or 0))
    return {"runs": runs, "strategies": strategies}
