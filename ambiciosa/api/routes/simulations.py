"""Simulation runs: start, list, progress (server-sent events), cancel, results, export."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from ...analysis import compare_runs, run_analysis
from ...persistence import Database, export_simulations, run_overview, strategy_summary
from ...simulation import Progress, SimulationRunner
from ...simulation.config import SimulationConfig
from ..deps import db, jsonable, parse_uuid, runner, seats_from_request
from ..models import SimulationCreate

router = APIRouter(tags=["simulations"])

PROGRESS_INTERVAL = 0.5  # seconds between progress events


def _progress_json(p: Progress) -> dict:
    return {
        "simulation_id": str(p.simulation_id),
        "status": p.status,
        "games_completed": p.games_completed,
        "games_requested": p.games_requested,
        "fraction": p.fraction,
        "elapsed_s": p.elapsed_s,
        "rate": p.rate,
        "eta_s": p.eta_s,
        "error": p.error,
    }


def _stored_progress(row: dict) -> dict:
    """Progress of a run this server is not running (finished, or from another session)."""
    done, requested = row["n_games_completed"], row["n_games_requested"]
    elapsed = None
    if row.get("finished_at") and row.get("created_at"):
        elapsed = (row["finished_at"] - row["created_at"]).total_seconds()
    return {
        "simulation_id": str(row["simulation_id"]),
        "status": str(row["status"]),
        "games_completed": done,
        "games_requested": requested,
        "fraction": done / requested if requested else 1.0,
        "elapsed_s": elapsed,
        "rate": done / elapsed if elapsed else None,
        "eta_s": 0.0 if str(row["status"]) != "running" else None,
        "error": None,
    }


def _progress(run: SimulationRunner, database: Database, sim_id) -> dict:
    try:
        return _progress_json(run.progress(sim_id))
    except KeyError:
        return _stored_progress(database.get_simulation(sim_id))


@router.post("/simulations", status_code=201)
def start_simulation(body: SimulationCreate, database: Database = Depends(db), run: SimulationRunner = Depends(runner)):
    seats = seats_from_request(database, body.players)
    if any(s.player_type == "human" for s in seats):
        raise ValueError("simulations need automated players only")
    data = body.model_dump(exclude={"players"}, exclude_none=True)
    data["workers"] = min(body.workers or os.cpu_count() or 1, os.cpu_count() or 1)
    config = SimulationConfig(players=tuple(seats), **data)
    sim_id = run.start(config)
    return {"simulation_id": str(sim_id), "progress": _progress_json(run.progress(sim_id))}


@router.get("/simulations")
def list_simulations(source: str | None = Query(None, pattern="^(simulation|interactive)$"),
                     database: Database = Depends(db), run: SimulationRunner = Depends(runner)):
    rows = jsonable(database.list_simulations(source))
    for r in rows:
        if r["status"] == "running":
            try:
                live = run.progress(parse_uuid(r["simulation_id"]))
                r["n_games_completed"] = live.games_completed
            except KeyError:
                pass
    return rows


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str, database: Database = Depends(db), run: SimulationRunner = Depends(runner)):
    sid = parse_uuid(simulation_id, "simulation")
    row = database.get_simulation(sid)
    out = jsonable(row)
    out["progress"] = _progress(run, database, sid)
    names = {str(s.strategy_version_id): s.label() for s in
             (database.get_strategy(p["strategy_version_id"]) for p in row["config"]["players"]
              if p.get("strategy_version_id"))}
    for p in out["config"]["players"]:
        p["strategy_label"] = names.get(p.get("strategy_version_id"))
    return out


@router.get("/simulations/{simulation_id}/progress")
async def progress_stream(simulation_id: str, request: Request, database: Database = Depends(db),
                          run: SimulationRunner = Depends(runner)):
    """Server-sent events: one `progress` event every half second until the run ends."""
    sid = parse_uuid(simulation_id, "simulation")
    database.get_simulation(sid)  # 404 for unknown runs, before the stream starts

    async def events():
        while True:
            data = await asyncio.to_thread(_progress, run, database, sid)
            yield f"event: progress\ndata: {json.dumps(data)}\n\n"
            if data["status"] in ("completed", "cancelled", "failed") or await request.is_disconnected():
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(PROGRESS_INTERVAL)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/simulations/{simulation_id}/cancel")
def cancel(simulation_id: str, database: Database = Depends(db), run: SimulationRunner = Depends(runner)):
    sid = parse_uuid(simulation_id, "simulation")
    try:
        live = run.progress(sid)
    except KeyError:
        live = None
    if live is None or live.done:
        status = live.status if live else str(database.get_simulation(sid)["status"])
        raise HTTPException(409, f"run is not in progress (status {status})")
    run.cancel(sid)
    return _progress(run, database, sid)


@router.delete("/simulations/{simulation_id}")
def delete(simulation_id: str, database: Database = Depends(db), run: SimulationRunner = Depends(runner)):
    sid = parse_uuid(simulation_id, "simulation")
    if str(database.get_simulation(sid)["status"]) == "running":
        raise HTTPException(409, "cancel the run before deleting it")
    database.delete_simulation(sid)
    return {"result": "deleted"}


@router.get("/simulations/{simulation_id}/stats")
def stats(simulation_id: str, database: Database = Depends(db)):
    sid = parse_uuid(simulation_id, "simulation")
    database.get_simulation(sid)
    return jsonable({"overview": run_overview(database, sid), "players": strategy_summary(database, sid)})


@router.get("/simulations/{simulation_id}/analysis")
def analysis(simulation_id: str, database: Database = Depends(db)):
    """Every metric of one run, as far as its recording level allows."""
    sid = parse_uuid(simulation_id, "simulation")
    return jsonable(run_analysis(database, sid))


GAME_SORTS = {
    "index": "g.game_index",
    "longest": "g.n_rounds DESC, g.game_index",
    "shortest": "g.n_rounds, g.game_index",
    "closest": "margin, g.game_index",
}


@router.get("/simulations/{simulation_id}/games")
def games(simulation_id: str, limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0),
          winner: int | None = Query(None, ge=0, le=5, description="only games won (or shared) by this seat"),
          status: str | None = Query(None, pattern="^(finished|unfinished|abandoned)$"),
          sort: str = Query("index", pattern="^(index|longest|shortest|closest)$"),
          database: Database = Depends(db)):
    """Games of a run with their scores, for the history viewer."""
    sid = parse_uuid(simulation_id, "simulation")
    database.get_simulation(sid)
    where, params = ["g.simulation_id = ?"], [str(sid)]
    if status:
        where.append("g.status = ?")
        params.append(status)
    if winner is not None:
        where.append("EXISTS (SELECT 1 FROM game_player w WHERE w.game_id = g.game_id AND w.seat = ? AND w.is_winner)")
        params.append(winner)
    base = (
        "SELECT g.game_id, g.game_index, g.status, g.n_rounds, "
        "list(gp.seat ORDER BY gp.seat) FILTER (WHERE gp.is_winner) AS winner_seats, "
        "list(gp.display_name ORDER BY gp.seat) FILTER (WHERE gp.is_winner) AS winners, "
        "list(gp.final_score ORDER BY gp.seat) AS scores, "
        "list(gp.play_order ORDER BY gp.seat) AS play_order, "
        "max(gp.final_score) - coalesce(max(gp.final_score) FILTER (WHERE NOT gp.is_winner), max(gp.final_score)) "
        "  AS margin "
        f"FROM game g JOIN game_player gp USING (game_id) WHERE {' AND '.join(where)} GROUP BY ALL"
    )
    total = database.query(f"SELECT count(*) n FROM ({base})", params)[0]["n"]
    rows = database.query(f"SELECT * FROM ({base}) g ORDER BY {GAME_SORTS[sort]} LIMIT ? OFFSET ?",
                          [*params, limit, offset])
    return jsonable({"total": total, "games": rows})


@router.get("/compare")
def compare(ids: str = Query(..., description="comma-separated simulation ids"), database: Database = Depends(db)):
    """Runs side by side, and each strategy's result in each run."""
    parsed = [parse_uuid(i.strip(), "simulation") for i in ids.split(",") if i.strip()]
    if not parsed:
        raise ValueError("give at least one simulation id")
    return jsonable(compare_runs(database, parsed))


@router.get("/simulations/{simulation_id}/export")
def export(simulation_id: str, format: str = Query("parquet", pattern="^(parquet|csv)$"),
           database: Database = Depends(db)):
    """A zip of one file per table, written to a temporary file and streamed (any size)."""
    sid = parse_uuid(simulation_id, "simulation")
    database.get_simulation(sid)
    tmp = Path(tempfile.mkdtemp(prefix="ambiciosa-export-"))
    try:
        files = export_simulations(database, [sid], tmp / "tables", format)
        archive = tmp / f"ambiciosa-{str(sid)[:8]}-{format}.zip"
        # Parquet files are already compressed; CSV compresses well.
        method = zipfile.ZIP_STORED if format == "parquet" else zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(archive, "w", method) as zf:
            for f in files:
                zf.write(f, Path(f).name)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return FileResponse(archive, media_type="application/zip", filename=archive.name,
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))
