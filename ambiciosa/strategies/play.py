"""Connects strategies to games.

`AutomatedPlayers` builds one strategy and one random stream per automated
player. The streams are spawned from the game's seed after the engine's own
streams (playing order, dice), so random strategies never change the dice
sequence, and the same seed always reproduces the same game.
"""

from __future__ import annotations

import numpy as np

from ..engine import DecisionContext, DecisionResult, Game, GameConfig
from .base import Strategy
from .spec import StrategySpec


class AutomatedPlayers:
    """Decision function for every automated seat of one game. Create once per game."""

    def __init__(self, game: Game) -> None:
        self.game = game
        streams = game.seed_sequence.spawn(game.config.n_players)
        self._strategies: dict[int, tuple[Strategy, np.random.Generator]] = {}
        for player, ss in zip(game.players, streams, strict=True):
            if player.config.player_type != "automated":
                continue
            spec = player.config.strategy
            if not isinstance(spec, StrategySpec):
                raise ValueError(f"automated player {player.config.name!r} needs a StrategySpec")
            self._strategies[player.seat] = (spec.build(), np.random.default_rng(ss))

    def is_automated(self, seat: int) -> bool:
        return seat in self._strategies

    def __call__(self, seat: int, ctx: DecisionContext) -> DecisionResult:
        try:
            strategy, rng = self._strategies[seat]
        except KeyError:
            raise ValueError(f"seat {seat} is a human player; it needs a decision from the user") from None
        return strategy.decide(ctx, rng)


def play_automated(
    config: GameConfig,
    seed: int | np.random.SeedSequence | None,
    *,
    record_history: bool = True,
) -> Game:
    """Play a game between automated players to the end and return it."""
    game = Game(config, seed, record_history=record_history)
    game.play_to_end(AutomatedPlayers(game))
    return game
