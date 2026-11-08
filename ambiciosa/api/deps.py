"""Shared helpers for the route modules."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request

from ..persistence import Database
from ..simulation import SimulationRunner
from ..simulation.config import SeatConfig
from .models import SeatRequest
from .sessions import GameSessions


def db(request: Request) -> Database:
    return request.app.state.db


def runner(request: Request) -> SimulationRunner:
    return request.app.state.runner


def sessions(request: Request) -> GameSessions:
    return request.app.state.sessions


def parse_uuid(value: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(404, f"{what} {value!r} is not a valid id") from None


def seats_from_request(database: Database, players: list[SeatRequest]) -> list[SeatConfig]:
    """Turn seats that name stored strategy versions into seats that carry the specs."""
    seats = []
    for p in players:
        if p.player_type == "human":
            if p.strategy_version_id is not None:
                raise ValueError(f"human seat {p.name!r} cannot have a strategy")
            seats.append(SeatConfig(name=p.name, player_type="human"))
            continue
        if p.strategy_version_id is None:
            raise ValueError(f"automated seat {p.name!r} needs a strategy_version_id")
        try:
            spec = database.get_strategy(p.strategy_version_id)
        except KeyError:
            raise ValueError(f"seat {p.name!r}: no strategy version {p.strategy_version_id}") from None
        seats.append(SeatConfig(name=p.name, strategy=spec))
    return seats


def jsonable(value: Any) -> Any:
    """DuckDB rows contain UUIDs, datetimes and enum strings: make them JSON-friendly."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def spec_json(spec, *, archived: bool | None = None, versions: int | None = None) -> dict[str, Any]:
    data = json.loads(spec.model_dump_json())
    data["label"] = spec.label()
    if archived is not None:
        data["archived"] = archived
    if versions is not None:
        data["n_versions"] = versions
    return data
