"""Interactive games (Play mode).

Each interactive game is one `Game` driven step by step by the browser. The
client asks for every throw, including the bots', so it can show them one at
a time; after a bot's positive throw the bot's decision (and its reason) is
applied on the server straight away. Humans answer with a decision.

Decision 10: interactive games are stored in the same tables as simulations,
as a one-game run with `source = 'interactive'`, recording level `full`, and
the strategy reasons kept. The run row is created when the game starts and
the game's rows are written when it ends (finished, or abandoned).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..engine import Decision, Game, GameStatus, ThrowRecord, TurnRecord
from ..persistence import Database
from ..simulation.config import SimulationConfig
from ..simulation.recorder import BatchRecorder, game_id_for
from ..simulation.seeds import game_seed
from ..strategies import AutomatedPlayers


class GameActionError(ValueError):
    """An action that is not allowed in the game's current state (HTTP 409)."""


def _throw_json(r: ThrowRecord) -> dict[str, Any]:
    return {
        "throw_number": r.throw_number,
        "dice": [int(d) for d in r.dice],
        "symbols": "".join(d.symbol for d in r.dice),
        "score": r.score,
        "turn_points_after": r.turn_points_after,
        "decision": None if r.decision is None else r.decision.value,
        "reason": r.reason,
    }


def _turn_json(t: TurnRecord) -> dict[str, Any]:
    return {
        "seat": t.seat,
        "turn_number": t.turn_number,
        "round_number": t.round_number,
        "points": t.points,
        "end_reason": None if t.end_reason is None else t.end_reason.value,
        "turn_score": t.turn_score,
        "banked_after": t.banked_after,
        "throws": [_throw_json(r) for r in t.throws],
    }


@dataclass
class InteractiveGame:
    simulation_id: uuid.UUID
    config: SimulationConfig
    game: Game
    bots: AutomatedPlayers
    stored: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def game_id(self) -> uuid.UUID:
        return game_id_for(self.simulation_id, 0)

    # ------------------------------------------------------------ views

    def state(self, history_turns: int | None = None) -> dict[str, Any]:
        g = self.game
        seat = g.current_seat
        history = g.history if history_turns is None else g.history[-history_turns:]
        return {
            "game_id": str(self.game_id),
            "simulation_id": str(self.simulation_id),
            "status": "abandoned" if self.stored and not g.is_over else g.status.value,
            "awaiting": g.awaiting if not (self.stored and not g.is_over) else "finished",
            "round_number": g.round_number,
            "current_seat": seat,
            "current_player_type": None if seat is None else g.players[seat].config.player_type,
            "play_order": list(g.play_order),
            "target": g.config.target,
            "end_rule": g.config.end_rule.value,
            "max_turns": g.config.max_turns,
            "scoring": g.config.scoring.as_dict(),
            "winners": list(g.winners),
            "players": [
                {
                    "seat": p.seat,
                    "name": p.config.name,
                    "player_type": p.config.player_type,
                    "strategy": None if p.config.strategy is None else {
                        "name": p.config.strategy.label(),
                        "type": p.config.strategy.type,
                        "strategy_version_id": str(p.config.strategy.strategy_version_id),
                    },
                    "score": p.score,
                    "turns_taken": p.turns_taken,
                    "total_throws": p.total_throws,
                    "busts": p.busts,
                }
                for p in g.players
            ],
            "current_turn": None if g.current_turn is None else _turn_json(g.current_turn),
            "history": [_turn_json(t) for t in history],
            "n_turns": len(g.history),
        }

    # ---------------------------------------------------------- actions

    def throw(self, db: Database) -> dict[str, Any]:
        with self.lock:
            g = self.game
            if self.stored or g.awaiting != "throw":
                raise GameActionError(f"cannot throw now: the game is awaiting {self.state()['awaiting']!r}")
            seat = g.current_seat
            turns_before = len(g.history)
            record = g.throw()
            event: dict[str, Any] = {"seat": seat, "throw": _throw_json(record), "bot_decision": None}
            if g.awaiting == "decision" and self.bots.is_automated(seat):
                result = self.bots(seat, g.decision_context())
                g.decide(result.decision, result.reason or None)
                event["bot_decision"] = {"decision": result.decision.value, "reason": result.reason}
                event["throw"] = _throw_json(record)  # now carries the decision and reason
            event["turn_ended"] = len(g.history) > turns_before
            event["turn"] = _turn_json(g.history[-1]) if event["turn_ended"] else None
            if g.is_over:
                self._store(db)
            return {"event": event, "state": self.state()}

    def decide(self, db: Database, decision: Decision) -> dict[str, Any]:
        with self.lock:
            g = self.game
            if self.stored or g.awaiting != "decision":
                raise GameActionError(f"cannot decide now: the game is awaiting {self.state()['awaiting']!r}")
            seat = g.current_seat
            if self.bots.is_automated(seat):
                raise GameActionError("the current player is automated; its decisions are made by its strategy")
            turns_before = len(g.history)
            g.decide(decision, "chosen by the player")
            ended = len(g.history) > turns_before
            event = {
                "seat": seat,
                "decision": decision.value,
                "turn_ended": ended,
                "turn": _turn_json(g.history[-1]) if ended else None,
            }
            return {"event": event, "state": self.state()}

    def abandon(self, db: Database) -> dict[str, Any]:
        with self.lock:
            if not self.stored:
                self._store(db)
            return {"state": self.state()}

    def _store(self, db: Database) -> None:
        recorder = BatchRecorder(self.simulation_id, "full", keep_reasons=True)
        recorder.add(self.game, 0)
        db.insert_batch(self.simulation_id, recorder.to_arrow())
        db.set_status(self.simulation_id, "completed" if self.game.is_over else "cancelled")
        self.stored = True


class GameSessions:
    """The interactive games of this server process, by game id."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._games: dict[uuid.UUID, InteractiveGame] = {}
        self._lock = threading.Lock()

    def create(self, config: SimulationConfig) -> InteractiveGame:
        if config.n_games != 1:
            raise ValueError("an interactive game is a single game")
        specs = [None if s.strategy is None else self.db.resolve_strategy(s.strategy) for s in config.players]
        config = config.with_strategies(specs).model_copy(update={"record_level": "full", "workers": 1})
        simulation_id = uuid.uuid4()
        game = Game(config.game_config(), game_seed(config.master_seed, 0))
        session = InteractiveGame(simulation_id, config, game, AutomatedPlayers(game))
        self.db.create_simulation(
            simulation_id,
            name=config.name,
            master_seed=config.master_seed,
            n_games_requested=1,
            record_level="full",
            config=config.stored_dict(),
            source="interactive",
        )
        with self._lock:
            self._games[session.game_id] = session
        return session

    def get(self, game_id: uuid.UUID) -> InteractiveGame:
        try:
            return self._games[game_id]
        except KeyError:
            raise KeyError(f"no interactive game {game_id} in this session; finished games are in the history") from None

    def list(self) -> list[InteractiveGame]:
        return list(self._games.values())

    def active(self) -> list[InteractiveGame]:
        return [s for s in self._games.values() if not s.stored and s.game.status is GameStatus.IN_PROGRESS]
