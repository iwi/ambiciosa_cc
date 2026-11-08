"""Strategy 4: continue with a fixed probability."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from ..engine import Decision, DecisionContext, DecisionResult
from .base import Params, StrategyType, register


class RandomParams(Params):
    p_continue: float = Field(0.75, ge=0, le=1, title="Chance of continuing", description="Probability of choosing CONTINUE")


@dataclass(frozen=True)
class RandomStrategy:
    params: RandomParams

    def decide(self, ctx: DecisionContext, rng) -> DecisionResult:
        p = self.params.p_continue
        draw = float(rng.random())
        pct = f"{p:.0%}"
        if draw < p:
            return DecisionResult(Decision.CONTINUE, f"random draw {draw:.3f} < {p:g} ({pct} continue)")
        return DecisionResult(Decision.STOP, f"random draw {draw:.3f} >= {p:g} ({pct} continue)")


RANDOM = register(
    StrategyType(
        name="random",
        title="Random decision",
        description="Continue or stop at random with a set probability of continuing.",
        params_model=RandomParams,
        factory=RandomStrategy,
    )
)
