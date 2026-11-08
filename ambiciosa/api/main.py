"""The FastAPI application.

All endpoints live under `/api`; everything else serves the built React app
(`ambiciosa/web_dist`), so `ambiciosa serve` is the only command needed.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .. import __version__
from ..persistence import Database, StrategyConflict
from ..simulation import SimulationRunner
from ..strategies import PRESETS
from .routes import games, simulations, strategies
from .sessions import GameActionError, GameSessions


def default_static_dir() -> Path | None:
    path = Path(str(files("ambiciosa").joinpath("web_dist")))
    return path if (path / "index.html").is_file() else None


def seed_presets(db: Database) -> int:
    """Put the presets into an empty library (only once, so deleted presets stay deleted)."""
    if db.query("SELECT count(*) n FROM strategy")[0]["n"]:
        return 0
    for p in PRESETS:
        db.resolve_strategy(p)
    return len(PRESETS)


def create_app(
    database: Database | str | Path = ":memory:",
    *,
    static_dir: Path | None | bool = True,
    mp_context: str = "spawn",
) -> FastAPI:
    db = database if isinstance(database, Database) else Database(database)
    interrupted = db.mark_interrupted_runs()
    seed_presets(db)

    app = FastAPI(title="Ambiciosa Simulator", version=__version__,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.db = db
    app.state.runner = SimulationRunner(db, mp_context=mp_context)
    app.state.sessions = GameSessions(db)
    app.state.interrupted_runs = interrupted

    def error(status: int, message: str) -> JSONResponse:
        return JSONResponse({"detail": message}, status_code=status)

    @app.exception_handler(KeyError)
    async def not_found(_: Request, exc: KeyError):
        return error(404, str(exc.args[0]) if exc.args else "not found")

    @app.exception_handler(GameActionError)
    async def conflict(_: Request, exc: GameActionError):
        return error(409, str(exc))

    @app.exception_handler(StrategyConflict)
    async def strategy_conflict(_: Request, exc: StrategyConflict):
        return error(409, str(exc))

    @app.exception_handler(ValidationError)
    async def invalid(_: Request, exc: ValidationError):
        msgs = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]
        return error(422, "; ".join(msgs))

    @app.exception_handler(ValueError)
    async def bad_value(_: Request, exc: ValueError):
        return error(422, str(exc))

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError):
        msgs = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return error(422, "; ".join(msgs))

    @app.get("/api/info", tags=["info"])
    def info():
        return {
            "version": __version__,
            "database": db.path,
            "cpu_count": os.cpu_count(),
            "interrupted_runs_marked_failed": app.state.interrupted_runs,
        }

    for module in (strategies, games, simulations):
        app.include_router(module.router, prefix="/api")

    if static_dir is True:
        static_dir = default_static_dir()
    if static_dir:
        static = Path(static_dir)
        app.mount("/assets", StaticFiles(directory=static / "assets", check_dir=False), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return error(404, f"no endpoint /{path}")
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")  # client-side routes

    return app
