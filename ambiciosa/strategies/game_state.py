"""Strategy 5: the stopping threshold depends on the game situation.

Rules, checked in this order:
  1. Close to winning: if the points still needed (target - banked score) are
     at most `close_to_win_points`, use `close_threshold`. With no
     `close_threshold`, keep throwing: the turn ends by itself when the target
     is reached.
  2. Leading (strictly ahead of every opponent, or playing alone): use
     `leading_threshold`.
  3. Otherwise (behind or tied, since a tie is not ahead): use `trailing_threshold`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from ..engine import Decision, DecisionContext, DecisionResult
from .base import Params, StrategyType, register
from .threshold import threshold_rule


class GameStateParams(Params):
    leading_threshold: int = Field(30, ge=1, title="When ahead, bank at", description="Threshold when strictly ahead (conservative)")
    trailing_threshold: int = Field(60, ge=1, title="When behind or tied, bank at", description="Threshold when behind or tied (aggressive)")
    close_to_win_points: int | None = Field(
        100, ge=1, title="Close to winning within", description="Apply the close-to-win rule when this many points or fewer are still needed; empty to disable"
    )
    close_threshold: int | None = Field(
        None, ge=1, title="When close to winning, bank at", description="Threshold when close to winning; empty means keep throwing until the target is reached"
    )


@dataclass(frozen=True)
class GameStateStrategy:
    params: GameStateParams

    def decide(self, ctx: DecisionContext, rng=None) -> DecisionResult:
        p = self.params
        if p.close_to_win_points is not None and ctx.points_to_target <= p.close_to_win_points:
            situation = f"close to winning ({ctx.points_to_target} needed)"
            if p.close_threshold is None:
                return DecisionResult(Decision.CONTINUE, f"{situation}: going for the win")
            return _with_situation(situation, threshold_rule(ctx.turn_points, p.close_threshold))
        if ctx.is_leading:
            situation = "playing alone" if ctx.num_opponents == 0 else f"leading by {ctx.gap_to_leader}"
            return _with_situation(situation, threshold_rule(ctx.turn_points, p.leading_threshold))
        situation = "tied for the lead" if ctx.gap_to_leader == 0 else f"trailing by {-ctx.gap_to_leader}"
        return _with_situation(situation, threshold_rule(ctx.turn_points, p.trailing_threshold))


def _with_situation(situation: str, result: DecisionResult) -> DecisionResult:
    return DecisionResult(result.decision, f"{situation}: {result.reason}")


GAME_STATE = register(
    StrategyType(
        name="game_state",
        title="Game-state-dependent",
        description="Use one threshold when leading, another when behind or tied, and a third when close to winning.",
        params_model=GameStateParams,
        factory=GameStateStrategy,
    )
)
