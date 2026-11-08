"""Turn and game management (spec 2.3-2.5, decisions 1-3 and the equal-turns details).

`Game` is a step-wise state machine. The caller alternates between
`throw()` and, after a positive throw that does not reach the target,
`decide()`. Interactive play drives it one step at a time; automated play
uses `play_to_end()` with a decision function. The engine never chooses a
decision itself.

Turn rules:
  * A throw scoring 0 ends the turn; the turn scores 0.
  * A throw scoring < 0 ends the turn; the turn scores that negative value,
    whatever was accumulated before.
  * A positive throw is added to the turn total. If banked score + turn total
    reaches the target, the turn ends and is banked automatically (no STOP
    needed). Otherwise the player chooses STOP (bank) or CONTINUE (throw again).

Game end:
  * first_to_target: the game ends as soon as a player reaches the target.
  * equal_turns: once anyone has reached the target, the current round is
    completed so every player has had the same number of turns; the highest
    total wins and an exact tie is a shared win.
  * If `max_turns` rounds are completed without a result, the game ends with
    status UNFINISHED and no winner.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np

from .dice import DiceSource, RandomDice, Throw, normalise_weights
from .scoring import DEFAULT_SCORING, Scoring
from .state import Decision, DecisionContext, DecisionResult, TurnEndReason

MAX_PLAYERS = 6


class EndRule(str, Enum):
    FIRST_TO_TARGET = "first_to_target"
    EQUAL_TURNS = "equal_turns"


class GameStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    UNFINISHED = "unfinished"  # max_turns reached without a winner


class IllegalAction(RuntimeError):
    """Raised when throw()/decide() is called at the wrong moment."""


@dataclass(frozen=True)
class PlayerConfig:
    name: str
    player_type: Literal["human", "automated"] = "automated"
    strategy: Any = None  # opaque to the engine; filled in by the strategy layer

    def __post_init__(self) -> None:
        if self.player_type not in ("human", "automated"):
            raise ValueError(f"player_type must be 'human' or 'automated', got {self.player_type!r}")


@dataclass(frozen=True)
class GameConfig:
    players: tuple[PlayerConfig, ...]
    target: int = 1000
    end_rule: EndRule = EndRule.FIRST_TO_TARGET
    max_turns: int = 500
    face_weights: tuple[float, ...] | None = None  # order 9, 10, J, Q, K, A; None = fair dice
    scoring: Scoring = DEFAULT_SCORING             # decision 11: configurable points

    def __post_init__(self) -> None:
        players = tuple(self.players)
        if not 1 <= len(players) <= MAX_PLAYERS:
            raise ValueError(f"a game needs 1 to {MAX_PLAYERS} players, got {len(players)}")
        if self.target <= 0:
            raise ValueError("target must be positive")
        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        object.__setattr__(self, "players", players)
        object.__setattr__(self, "end_rule", EndRule(self.end_rule))
        object.__setattr__(self, "face_weights", normalise_weights(self.face_weights))
        if isinstance(self.scoring, dict):
            object.__setattr__(self, "scoring", Scoring.from_dict(self.scoring))
        elif not isinstance(self.scoring, Scoring):
            raise ValueError("scoring must be a Scoring or a mapping of score names to values")

    @property
    def n_players(self) -> int:
        return len(self.players)


@dataclass(slots=True)
class ThrowRecord:
    throw_number: int
    dice: Throw
    score: int
    turn_points_after: int          # accumulated total, or the bust value if the throw ended the turn
    decision: Decision | None = None  # None when the throw ended the turn
    reason: str | None = None


@dataclass(slots=True)
class TurnRecord:
    seat: int
    turn_number: int                # this player's turn count, starting at 1
    round_number: int
    throws: list[ThrowRecord] = field(default_factory=list)
    points: int = 0                 # positive total accumulated so far
    end_reason: TurnEndReason | None = None
    turn_score: int | None = None
    banked_after: int | None = None

    @property
    def n_throws(self) -> int:
        return len(self.throws)


@dataclass(slots=True)
class PlayerState:
    seat: int
    config: PlayerConfig
    score: int = 0
    turns_taken: int = 0
    total_throws: int = 0
    busts: int = 0
    reached_target: bool = False


Awaiting = Literal["throw", "decision", "finished"]
Decider = Callable[[int, DecisionContext], "DecisionResult | Decision"]


class Game:
    def __init__(
        self,
        config: GameConfig,
        seed: int | np.random.SeedSequence | None = None,
        *,
        dice: DiceSource | None = None,
        play_order: Sequence[int] | None = None,
        record_history: bool = True,
    ) -> None:
        self.config = config
        self.seed_sequence = (
            seed if isinstance(seed, np.random.SeedSequence) else np.random.SeedSequence(seed)
        )
        # Independent streams: [0] playing order, [1] dice. Further streams
        # (e.g. for random strategies) can be spawned later without affecting these.
        order_ss, dice_ss = self.seed_sequence.spawn(2)

        n = config.n_players
        if play_order is None:
            order = [int(x) for x in np.random.default_rng(order_ss).permutation(n)]
        else:
            order = [int(x) for x in play_order]
            if sorted(order) != list(range(n)):
                raise ValueError(f"play_order must be a permutation of 0..{n - 1}, got {order}")
        self.play_order: tuple[int, ...] = tuple(order)

        self._dice: DiceSource = dice if dice is not None else RandomDice(dice_ss, config.face_weights)
        self._score_table = config.scoring.table
        self._target = config.target
        self.players: tuple[PlayerState, ...] = tuple(
            PlayerState(seat=i, config=p) for i, p in enumerate(config.players)
        )
        self.record_history = record_history
        self.history: list[TurnRecord] = []

        self.status = GameStatus.IN_PROGRESS
        self.winners: tuple[int, ...] = ()
        self.round_number = 1
        self._order_pos = 0
        self._awaiting: Awaiting = "throw"
        self._turn: TurnRecord | None = None
        # Each seat's best opponent score; scores change only when a turn ends, so this is
        # refreshed there instead of being recomputed for every decision.
        self._best_other: list[int | None] = [None] * n
        self._refresh_best_other()

    # ----------------------------------------------------------------- queries

    @property
    def awaiting(self) -> Awaiting:
        return self._awaiting

    @property
    def is_over(self) -> bool:
        return self.status is not GameStatus.IN_PROGRESS

    @property
    def current_seat(self) -> int | None:
        return None if self.is_over else self.play_order[self._order_pos]

    @property
    def current_player(self) -> PlayerState | None:
        seat = self.current_seat
        return None if seat is None else self.players[seat]

    @property
    def current_turn(self) -> TurnRecord | None:
        return self._turn

    @property
    def winner(self) -> int | None:
        """The single winner's seat, or None if there is no winner or a shared win."""
        return self.winners[0] if len(self.winners) == 1 else None

    def scores(self) -> tuple[int, ...]:
        return tuple(p.score for p in self.players)

    def decision_context(self) -> DecisionContext:
        """The current player's view of the game, for a strategy."""
        if self.status is not GameStatus.IN_PROGRESS:
            raise IllegalAction("the game is over")
        seat = self.play_order[self._order_pos]
        player = self.players[seat]
        score = player.score
        best = self._best_other[seat]
        turn = self._turn
        target = self._target
        if turn is not None:
            throws = turn.throws
            points, n_throws, last, turn_number = (
                turn.points, len(throws), throws[-1].score if throws else 0, turn.turn_number)
        else:
            points, n_throws, last, turn_number = 0, 0, 0, player.turns_taken + 1
        # Positional, in field order (see DecisionContext).
        return DecisionContext(
            points, n_throws, last, score, best,
            0 if best is None else score - best,       # gap_to_leader
            target - score,                            # points_to_target
            len(self.players) - 1,                     # num_opponents
            True if best is None else score > best,    # is_leading
            turn_number, target,
        )

    def _refresh_best_other(self) -> None:
        scores = [p.score for p in self.players]
        if len(scores) == 1:
            self._best_other[0] = None
            return
        for i in range(len(scores)):
            self._best_other[i] = max(s for j, s in enumerate(scores) if j != i)

    # ----------------------------------------------------------------- actions

    def throw(self) -> ThrowRecord:
        if self._awaiting != "throw":
            raise IllegalAction(f"cannot throw now: game is awaiting {self._awaiting!r}")
        player = self.players[self.play_order[self._order_pos]]
        if self._turn is None:
            player.turns_taken += 1
            self._turn = TurnRecord(
                seat=player.seat, turn_number=player.turns_taken, round_number=self.round_number
            )
        turn = self._turn

        dice = self._dice.roll()
        a, b, c = dice
        points = self._score_table[36 * a + 6 * b + c]
        player.total_throws += 1

        if points <= 0:
            record = ThrowRecord(len(turn.throws) + 1, dice, points, points)
            turn.throws.append(record)
            reason = TurnEndReason.BUST_ZERO if points == 0 else TurnEndReason.BUST_NEGATIVE
            self._end_turn(reason, points)
            return record

        turn.points += points
        record = ThrowRecord(len(turn.throws) + 1, dice, points, turn.points)
        turn.throws.append(record)
        if player.score + turn.points >= self._target:
            self._end_turn(TurnEndReason.REACHED_TARGET, turn.points)
        else:
            self._awaiting = "decision"
        return record

    def decide(self, decision: Decision | str, reason: str | None = None) -> None:
        if self._awaiting != "decision":
            raise IllegalAction(f"cannot decide now: game is awaiting {self._awaiting!r}")
        if decision.__class__ is not Decision:
            decision = Decision(decision)
        turn = self._turn
        assert turn is not None
        last = turn.throws[-1]
        last.decision = decision
        last.reason = reason
        if decision is Decision.STOP:
            self._end_turn(TurnEndReason.STOP, turn.points)
        else:
            self._awaiting = "throw"

    def play_to_end(self, decider: Decider) -> None:
        """Play automatically until the game ends.

        `decider(seat, context)` is called after every positive throw that
        does not reach the target, and returns a Decision or DecisionResult.
        """
        throw, decide, context = self.throw, self.decide, self.decision_context
        in_progress = GameStatus.IN_PROGRESS
        while self.status is in_progress:
            throw()
            if self._awaiting == "decision":
                result = decider(self.play_order[self._order_pos], context())
                if isinstance(result, DecisionResult):
                    decide(result.decision, result.reason or None)
                else:
                    decide(result)

    # --------------------------------------------------------------- internals

    def _end_turn(self, reason: TurnEndReason, turn_score: int) -> None:
        turn = self._turn
        assert turn is not None
        player = self.players[turn.seat]
        player.score += turn_score
        if turn_score:
            self._refresh_best_other()
        if reason in (TurnEndReason.BUST_ZERO, TurnEndReason.BUST_NEGATIVE):
            player.busts += 1
        if reason is TurnEndReason.REACHED_TARGET:
            player.reached_target = True
        turn.end_reason = reason
        turn.turn_score = turn_score
        turn.banked_after = player.score
        if self.record_history:
            self.history.append(turn)
        self._turn = None
        self._advance(player)

    def _advance(self, last_player: PlayerState) -> None:
        if self.config.end_rule is EndRule.FIRST_TO_TARGET and last_player.reached_target:
            self._finish(GameStatus.FINISHED, (last_player.seat,))
            return

        if self._order_pos == len(self.play_order) - 1:  # round complete
            if any(p.reached_target for p in self.players):  # only possible under equal_turns
                top = max(p.score for p in self.players)
                self._finish(GameStatus.FINISHED, tuple(p.seat for p in self.players if p.score == top))
                return
            if self.round_number >= self.config.max_turns:
                self._finish(GameStatus.UNFINISHED, ())
                return
            self.round_number += 1
            self._order_pos = 0
        else:
            self._order_pos += 1
        self._awaiting = "throw"

    def _finish(self, status: GameStatus, winners: tuple[int, ...]) -> None:
        self.status = status
        self.winners = tuple(sorted(winners))
        self._awaiting = "finished"
