"""Strategy 3: a points threshold and a throw limit, joined by AND or OR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from ..engine import Decision, DecisionContext, DecisionResult
from .base import Params, StrategyType, register


class CombinedParams(Params):
    threshold: int = Field(50, ge=1, title="Points to bank", description="Points condition: turn total reaches this")
    max_throws: int = Field(4, ge=1, title="Throws to bank", description="Throws condition: this many throws made")
    logic: Literal["or", "and"] = Field(
        "or", title="Combine conditions with", description="'or': stop when either condition holds; 'and': stop only when both hold"
    )


@dataclass(frozen=True)
class CombinedStrategy:
    params: CombinedParams

    def decide(self, ctx: DecisionContext, rng=None) -> DecisionResult:
        p = self.params
        points_met = ctx.turn_points >= p.threshold
        throws_met = ctx.throws_this_turn >= p.max_throws
        stop = (points_met or throws_met) if p.logic == "or" else (points_met and throws_met)
        detail = (
            f"points {ctx.turn_points}/{p.threshold} {'met' if points_met else 'not met'}, "
            f"throws {ctx.throws_this_turn}/{p.max_throws} {'met' if throws_met else 'not met'} "
            f"({p.logic.upper()})"
        )
        return DecisionResult(Decision.STOP if stop else Decision.CONTINUE, detail)


COMBINED = register(
    StrategyType(
        name="combined",
        title="Combined conditions",
        description="Combine a points threshold and a throw limit with AND or OR logic.",
        params_model=CombinedParams,
        factory=CombinedStrategy,
    )
)
