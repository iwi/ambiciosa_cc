"""Strategy types and the strategy library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...persistence import Database
from ...strategies import StrategySpec, list_types
from ..deps import db, parse_uuid, spec_json
from ..models import StrategyCreate, StrategyUpdate

router = APIRouter(tags=["strategies"])


@router.get("/strategy-types")
def strategy_types():
    return [
        {"name": t.name, "title": t.title, "description": t.description, "schema": t.json_schema()}
        for t in list_types()
    ]


def _library(database: Database, include_archived: bool) -> list[dict]:
    counts = {str(r["strategy_id"]): r["n"] for r in database.query(
        "SELECT strategy_id, count(*) n FROM strategy GROUP BY strategy_id")}
    archived = {str(r["strategy_id"]) for r in database.query("SELECT strategy_id FROM strategy_archive")}
    used = {str(r["strategy_id"]) for r in database.query(
        "SELECT DISTINCT s.strategy_id FROM strategy s JOIN game_player gp USING (strategy_version_id)")}
    out = []
    for spec in database.list_strategies(latest_only=True, include_archived=include_archived):
        sid = str(spec.strategy_id)
        item = spec_json(spec, archived=sid in archived, versions=counts[sid])
        item["has_results"] = sid in used
        out.append(item)
    return out


@router.get("/strategies")
def list_strategies(include_archived: bool = False, database: Database = Depends(db)):
    """The latest version of every strategy in the library."""
    return _library(database, include_archived)


@router.get("/strategies/{strategy_id}")
def strategy_versions(strategy_id: str, database: Database = Depends(db)):
    sid = parse_uuid(strategy_id, "strategy")
    versions = database.strategy_versions(sid)
    return {
        "strategy_id": str(sid),
        "archived": database.is_archived(sid),
        "versions": [spec_json(v) for v in versions],
    }


@router.post("/strategies", status_code=201)
def create_strategy(body: StrategyCreate, database: Database = Depends(db)):
    clash = [s for s in database.list_strategies(latest_only=True, include_archived=False)
             if s.name.casefold() == body.name.strip().casefold()]
    if clash:
        raise HTTPException(409, f"a strategy named {body.name!r} already exists; edit it to make a new version")
    spec = StrategySpec.create(body.name.strip(), body.type, body.params, body.description)
    return spec_json(database.resolve_strategy(spec), archived=False, versions=1)


@router.put("/strategies/{strategy_id}")
def update_strategy(strategy_id: str, body: StrategyUpdate, database: Database = Depends(db)):
    """Save an edit as the strategy's next version; results keep their old version."""
    sid = parse_uuid(strategy_id, "strategy")
    latest = database.strategy_versions(sid)[-1]
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        clash = [s for s in database.list_strategies(latest_only=True, include_archived=False)
                 if s.name.casefold() == changes["name"].casefold() and s.strategy_id != sid]
        if clash:
            raise HTTPException(409, f"another strategy is already named {changes['name']!r}")
    spec = database.add_version(latest, **changes)  # params are merged onto the latest ones
    return spec_json(spec, archived=database.is_archived(sid), versions=spec.version)


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: str, database: Database = Depends(db)):
    """Delete a strategy, or archive it if stored results use it."""
    return {"result": database.archive_strategy(parse_uuid(strategy_id, "strategy"))}


@router.post("/strategies/{strategy_id}/restore")
def restore_strategy(strategy_id: str, database: Database = Depends(db)):
    sid = parse_uuid(strategy_id, "strategy")
    database.strategy_versions(sid)
    database.restore_strategy(sid)
    return {"result": "restored"}
