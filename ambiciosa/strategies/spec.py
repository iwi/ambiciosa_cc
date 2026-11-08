"""Stored strategy definitions (spec 4.3).

A `StrategySpec` is one immutable version of a named strategy. Editing a
strategy produces a new version with the same `strategy_id`, so stored
results always point at the exact parameters that were used. The JSON form
matches the `strategy` table in the Phase 1 schema.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import Strategy, get_type


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    strategy_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version: int = Field(1, ge=1)
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_params(self) -> StrategySpec:
        validated = get_type(self.type).validate(self.params)
        # Store the full parameter set, defaults included, so a spec is self-describing.
        object.__setattr__(self, "params", validated.model_dump())
        return self

    @classmethod
    def create(cls, name: str, type: str, params: dict[str, Any] | None = None, description: str = "") -> StrategySpec:
        return cls(name=name, type=type, params=params or {}, description=description)

    def new_version(self, **changes: Any) -> StrategySpec:
        """A new version of this strategy with some fields changed (name, description, params)."""
        allowed = {"name", "description", "params"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)} in a new version; allowed: {sorted(allowed)}")
        data = self.model_dump()
        if "params" in changes:
            changes["params"] = {**self.params, **changes["params"]}
        data.update(changes)
        data.update(
            strategy_version_id=uuid.uuid4(),
            version=self.version + 1,
            created_at=datetime.now(UTC),
        )
        return StrategySpec.model_validate(data)

    def build(self) -> Strategy:
        st = get_type(self.type)
        return st.factory(st.validate(self.params))

    def label(self) -> str:
        """Short display text, e.g. 'Stop at 50 (v2)'."""
        return self.name if self.version == 1 else f"{self.name} (v{self.version})"

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> StrategySpec:
        return cls.model_validate_json(text)
