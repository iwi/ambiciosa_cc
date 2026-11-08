"""The strategy interface and the registry of strategy types.

A strategy type is a Pydantic parameters model plus a class that turns
validated parameters into decisions. Adding a type means writing those two
and calling `register()`; neither the engine nor the UI needs changes, because
forms are generated from each parameters model's JSON Schema.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..engine import DecisionContext, DecisionResult


class Strategy(Protocol):
    def decide(self, ctx: DecisionContext, rng: np.random.Generator) -> DecisionResult:
        """Return CONTINUE or STOP, with a short human-readable reason.

        Called only after a positive throw that leaves the player below the
        target. Strategies that use randomness must draw only from `rng`.
        """
        ...


class Params(BaseModel):
    """Base for strategy parameter models: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class StrategyType:
    name: str                                   # stored identifier, e.g. "threshold"
    title: str                                  # display name
    description: str
    params_model: type[Params]
    factory: Callable[[Any], Strategy]          # validated params -> Strategy

    def json_schema(self) -> dict[str, Any]:
        return self.params_model.model_json_schema()

    def validate(self, params: dict[str, Any] | Params) -> Params:
        if isinstance(params, self.params_model):
            return params
        return self.params_model.model_validate(params)


_REGISTRY: dict[str, StrategyType] = {}


def register(strategy_type: StrategyType) -> StrategyType:
    if strategy_type.name in _REGISTRY:
        raise ValueError(f"strategy type {strategy_type.name!r} is already registered")
    _REGISTRY[strategy_type.name] = strategy_type
    return strategy_type


def get_type(name: str) -> StrategyType:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown strategy type {name!r}; known types: {known}") from None


def list_types() -> list[StrategyType]:
    return list(_REGISTRY.values())
