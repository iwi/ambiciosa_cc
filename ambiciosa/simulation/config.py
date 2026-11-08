"""Simulation configuration: what to play, how many games and how much to record.

A config can be built in Python or loaded from YAML for the command line:

    name: Cautious vs bold
    n_games: 100000
    master_seed: 42            # optional; a random one is chosen and stored if omitted
    record_level: summary      # optional; default full up to 10,000 games, summary above
    target: 1000               # optional game rules, defaults as in the engine
    end_rule: first_to_target
    max_turns: 500
    face_weights: [1, 1, 1, 1, 1, 1]   # order 9, 10, J, Q, K, A
    scoring:                   # optional; any value left out keeps its default
      ace: 10
      king: 5
      three_aces: 100
      three_kings: 50
      three_tens: -100
      three_nines: -300
    players:
      - Stop at 30                                   # a preset, by name
      - name: Bold                                   # a seat with an inline strategy
        strategy: {type: threshold, params: {threshold: 60}}

`workers` and `chunk_size` only change speed, never results.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..engine import EndRule, GameConfig, PlayerConfig, Scoring, normalise_weights
from ..engine.scoring import DEFAULT_SCORING, SCORE_LIMIT
from ..engine.game import MAX_PLAYERS
from ..strategies import PRESETS, StrategySpec
from .seeds import MAX_SEED, new_master_seed

RecordLevel = Literal["summary", "turns", "full"]

_D = DEFAULT_SCORING


class ScoringRules(BaseModel):
    """Points per combination (decision 11); any value left out keeps its default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ace: int = Field(_D.ace, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Each Ace")
    king: int = Field(_D.king, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Each King")
    three_aces: int = Field(_D.three_aces, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Three Aces")
    three_kings: int = Field(_D.three_kings, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Three Kings")
    three_tens: int = Field(_D.three_tens, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Three 10s")
    three_nines: int = Field(_D.three_nines, ge=-SCORE_LIMIT, le=SCORE_LIMIT, strict=True, title="Three 9s")

    def to_engine(self) -> Scoring:
        return Scoring(**self.model_dump())

    @property
    def is_default(self) -> bool:
        return self.to_engine().is_default
FULL_RECORD_LIMIT = 10_000  # decision 7: full detail by default up to this many games


def find_preset(name: str) -> StrategySpec:
    for p in PRESETS:
        if p.name.casefold() == name.strip().casefold():
            return p
    known = ", ".join(repr(p.name) for p in PRESETS)
    raise ValueError(f"unknown preset strategy {name!r}; presets are {known}")


def _coerce_strategy(value: Any) -> Any:
    if isinstance(value, str):
        return find_preset(value)
    if isinstance(value, dict) and "name" not in value and "type" in value:
        params = value.get("params") or {}
        detail = ", ".join(f"{k}={v}" for k, v in params.items())
        return {**value, "name": f"{value['type']} ({detail})" if detail else value["type"]}
    return value


class SeatConfig(BaseModel):
    """One seat: an automated player with a strategy, or a human (interactive games only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    player_type: Literal["automated", "human"] = "automated"
    strategy: StrategySpec | None = None

    @model_validator(mode="after")
    def _strategy_matches_type(self) -> SeatConfig:
        if self.player_type == "automated" and self.strategy is None:
            raise ValueError(f"automated seat {self.name!r} needs a strategy")
        if self.player_type == "human" and self.strategy is not None:
            raise ValueError(f"human seat {self.name!r} cannot have a strategy")
        return self

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):               # "- Stop at 30"
            spec = find_preset(data)
            return {"name": spec.name, "strategy": spec}
        if isinstance(data, StrategySpec):
            return {"name": data.name, "strategy": data}
        if isinstance(data, dict):
            data = dict(data)
            if data.get("player_type") == "human":
                return data
            data["strategy"] = _coerce_strategy(data.get("strategy"))
            if "name" not in data:
                strategy = data["strategy"]
                if isinstance(strategy, StrategySpec):
                    data["name"] = strategy.name
                elif isinstance(strategy, dict) and "name" in strategy:
                    data["name"] = strategy["name"]
        return data


class SimulationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field("", max_length=200)
    n_games: int = Field(ge=1, le=100_000_000)
    master_seed: int = Field(default_factory=new_master_seed, ge=0, le=MAX_SEED)
    players: tuple[SeatConfig, ...] = Field(min_length=1, max_length=MAX_PLAYERS)
    target: int = Field(1000, gt=0)
    end_rule: EndRule = EndRule.FIRST_TO_TARGET
    max_turns: int = Field(500, ge=1)
    face_weights: tuple[float, ...] | None = None
    scoring: ScoringRules = Field(default_factory=ScoringRules)
    record_level: RecordLevel | None = None
    workers: int = Field(default_factory=lambda: os.cpu_count() or 1, ge=1, le=256)
    chunk_size: int = Field(1000, ge=1, le=1_000_000)

    @field_validator("face_weights")
    @classmethod
    def _weights(cls, v: tuple[float, ...] | None) -> tuple[float, ...] | None:
        return None if v is None else normalise_weights(v)

    @model_validator(mode="after")
    def _defaults(self) -> SimulationConfig:
        if self.record_level is None:
            level = "full" if self.n_games <= FULL_RECORD_LIMIT else "summary"
            object.__setattr__(self, "record_level", level)
        if not self.name:
            names = " vs ".join(s.strategy.label() if s.strategy else s.name for s in self.players)
            object.__setattr__(self, "name", names[:200])
        return self

    # ------------------------------------------------------------- conversions

    def game_config(self) -> GameConfig:
        return GameConfig(
            players=tuple(PlayerConfig(s.name, s.player_type, strategy=s.strategy) for s in self.players),
            target=self.target,
            end_rule=self.end_rule,
            max_turns=self.max_turns,
            face_weights=self.face_weights,
            scoring=self.scoring.to_engine(),
        )

    def strategies(self) -> list[StrategySpec]:
        """Distinct strategy versions used, in seat order."""
        seen: dict[Any, StrategySpec] = {}
        for s in self.players:
            if s.strategy is not None:
                seen.setdefault(s.strategy.strategy_version_id, s.strategy)
        return list(seen.values())

    @property
    def has_humans(self) -> bool:
        return any(s.player_type == "human" for s in self.players)

    def with_strategies(self, specs: list[StrategySpec | None]) -> SimulationConfig:
        """A copy with each seat's strategy replaced (one entry per seat, None for humans)."""
        if len(specs) != len(self.players):
            raise ValueError("need one strategy per seat")
        seats = tuple(
            SeatConfig(name=s.name, player_type=s.player_type, strategy=spec)
            for s, spec in zip(self.players, specs, strict=True)
        )
        return self.model_copy(update={"players": seats})

    def stored_dict(self) -> dict[str, Any]:
        """The form kept in simulation.config: seats point at strategy versions, not copies of them."""
        data = self.model_dump(mode="json", exclude={"players"})
        data["players"] = [
            {
                "name": s.name,
                "player_type": s.player_type,
                "strategy_version_id": None if s.strategy is None else str(s.strategy.strategy_version_id),
            }
            for s in self.players
        ]
        return data

    @classmethod
    def from_stored(cls, data: dict[str, Any] | str, specs: dict[str, StrategySpec]) -> SimulationConfig:
        """Rebuild a config from simulation.config and the strategy versions it refers to."""
        data = dict(json.loads(data) if isinstance(data, str) else data)
        data["players"] = [
            {"name": p["name"], "player_type": "human"}
            if p.get("player_type") == "human"
            else {"name": p["name"], "strategy": specs[str(p["strategy_version_id"])]}
            for p in data["players"]
        ]
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path, **overrides: Any) -> SimulationConfig:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping at the top level")
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(data)
