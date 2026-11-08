"""Strategy 2: keep throwing until a maximum number of throws, then stop."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from ..engine import Decision, DecisionContext, DecisionResult
from .base import Params, StrategyType, register


class MaxThrowsParams(Params):
    max_throws: int = Field(4, ge=1, title="Throws per turn", description="Never make more than this many throws in a turn")


@dataclass(frozen=True)
class MaxThrowsStrategy:
    params: MaxThrowsParams

    def decide(self, ctx: DecisionContext, rng=None) -> DecisionResult:
        n, limit = ctx.throws_this_turn, self.params.max_throws
        if n >= limit:
            return DecisionResult(Decision.STOP, f"{n} throws made, limit {limit}")
        return DecisionResult(Decision.CONTINUE, f"{n} of {limit} throws made")


MAX_THROWS = register(
    StrategyType(
        name="max_throws",
        title="Maximum number of throws",
        description="Keep throwing until a set number of throws has been made in the turn.",
        params_model=MaxThrowsParams,
        factory=MaxThrowsStrategy,
    )
)
