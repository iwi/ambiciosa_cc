"""Strategy 1: stop once the turn total reaches a threshold."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from ..engine import Decision, DecisionContext, DecisionResult
from .base import Params, StrategyType, register


class ThresholdParams(Params):
    threshold: int = Field(50, ge=1, title="Bank at", description="Stop when the turn total reaches this many points")


def threshold_rule(turn_points: int, threshold: int) -> DecisionResult:
    if turn_points >= threshold:
        return DecisionResult(Decision.STOP, f"turn total {turn_points} reached threshold {threshold}")
    return DecisionResult(Decision.CONTINUE, f"turn total {turn_points} below threshold {threshold}")


@dataclass(frozen=True)
class ThresholdStrategy:
    params: ThresholdParams

    def decide(self, ctx: DecisionContext, rng=None) -> DecisionResult:
        return threshold_rule(ctx.turn_points, self.params.threshold)


THRESHOLD = register(
    StrategyType(
        name="threshold",
        title="Fixed stopping threshold",
        description="Stop when the accumulated score for the turn reaches a set number of points.",
        params_model=ThresholdParams,
        factory=ThresholdStrategy,
    )
)
