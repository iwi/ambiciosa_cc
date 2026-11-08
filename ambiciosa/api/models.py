"""Request bodies for the HTTP API (responses are plain JSON objects)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..engine import Decision, EndRule
from ..simulation.config import ScoringRules


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyCreate(_Body):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyUpdate(_Body):
    """Fields to change; any change creates a new version."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    params: dict[str, Any] | None = None


class SeatRequest(_Body):
    name: str = Field(min_length=1, max_length=50)
    player_type: Literal["automated", "human"] = "automated"
    strategy_version_id: uuid.UUID | None = None


class RulesRequest(_Body):
    target: int = Field(1000, gt=0)
    end_rule: EndRule = EndRule.FIRST_TO_TARGET
    max_turns: int = Field(500, ge=1)
    face_weights: list[float] | None = None
    scoring: ScoringRules | None = None


class GameCreate(RulesRequest):
    players: list[SeatRequest] = Field(min_length=1, max_length=6)
    seed: int | None = Field(None, ge=0, le=2**64 - 1)


class SimulationCreate(RulesRequest):
    name: str = Field("", max_length=200)
    n_games: int = Field(ge=1, le=100_000_000)
    master_seed: int | None = Field(None, ge=0, le=2**64 - 1)
    record_level: Literal["summary", "turns", "full"] | None = None
    workers: int | None = Field(None, ge=1, le=256)
    chunk_size: int = Field(1000, ge=1, le=1_000_000)
    players: list[SeatRequest] = Field(min_length=1, max_length=6)


class DecisionRequest(_Body):
    decision: Decision
