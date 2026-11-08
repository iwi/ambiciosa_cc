"""Interactive play, and the stored history of any game."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...persistence import Database, game_history
from ...simulation.config import SimulationConfig
from ..deps import db, jsonable, parse_uuid, seats_from_request, sessions
from ..models import DecisionRequest, GameCreate
from ..sessions import GameSessions

router = APIRouter(tags=["games"])


@router.post("/games", status_code=201)
def create_game(body: GameCreate, database: Database = Depends(db), games: GameSessions = Depends(sessions)):
    seats = seats_from_request(database, body.players)
    data = body.model_dump(exclude={"players", "seed"}, exclude_none=True)
    if body.seed is not None:
        data["master_seed"] = body.seed
    config = SimulationConfig(n_games=1, players=tuple(seats), record_level="full", workers=1, **data)
    return games.create(config).state()


@router.get("/games")
def list_games(games: GameSessions = Depends(sessions)):
    """Interactive games of this server session (finished ones are also in the run list)."""
    return [
        {k: s.state(history_turns=0)[k] for k in ("game_id", "simulation_id", "status", "round_number", "players")}
        for s in games.list()
    ]


@router.get("/games/{game_id}")
def game_state(game_id: str, history_turns: int | None = None, games: GameSessions = Depends(sessions)):
    return games.get(parse_uuid(game_id, "game")).state(history_turns)


@router.post("/games/{game_id}/throw")
def throw(game_id: str, history_turns: int | None = 20, database: Database = Depends(db),
          games: GameSessions = Depends(sessions)):
    """Throw for the current player. For a bot, its decision is made at once and returned."""
    result = games.get(parse_uuid(game_id, "game")).throw(database)
    if history_turns is not None:
        result["state"]["history"] = result["state"]["history"][-history_turns:] if history_turns else []
    return result


@router.post("/games/{game_id}/decision")
def decide(game_id: str, body: DecisionRequest, database: Database = Depends(db),
           games: GameSessions = Depends(sessions)):
    """A human player's CONTINUE or STOP after a positive throw."""
    return games.get(parse_uuid(game_id, "game")).decide(database, body.decision)


@router.post("/games/{game_id}/abandon")
def abandon(game_id: str, database: Database = Depends(db), games: GameSessions = Depends(sessions)):
    """Stop a game early; it is stored with status 'abandoned'."""
    return games.get(parse_uuid(game_id, "game")).abandon(database)


@router.get("/games/{game_id}/history")
def history(game_id: str, database: Database = Depends(db)):
    """Players, turns and throws of a stored game (as much as its run recorded)."""
    gid = parse_uuid(game_id, "game")
    game = database.query("SELECT * FROM game WHERE game_id = ?", [str(gid)])
    if not game:
        raise KeyError(f"no stored game {gid}")
    return jsonable({"game": game[0], **game_history(database, gid)})
