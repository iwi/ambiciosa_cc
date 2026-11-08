"""Stored strategy definitions: validation, versioning, JSON, presets."""

import json

import pytest
from pydantic import ValidationError

from ambiciosa.strategies import PRESETS, StrategySpec, list_types


def test_create_fills_defaults_and_ids():
    s = StrategySpec.create("Bold", "combined", {"threshold": 80}, "Push hard")
    assert s.params == {"threshold": 80, "max_throws": 4, "logic": "or"}
    assert s.version == 1
    assert s.strategy_id != s.strategy_version_id
    assert s.label() == "Bold"


def test_spec_has_every_field_spec_4_3_requires():
    s = StrategySpec.create("X", "threshold")
    data = json.loads(s.to_json())
    for field in ("name", "description", "type", "params", "strategy_id"):
        assert field in data


def test_json_round_trip():
    s = StrategySpec.create("Bold", "game_state", {"close_threshold": 20})
    assert StrategySpec.from_json(s.to_json()) == s


def test_bad_params_rejected_at_creation():
    with pytest.raises(ValidationError):
        StrategySpec.create("Bad", "threshold", {"threshold": -5})
    with pytest.raises(ValidationError):
        StrategySpec.create("", "threshold")


def test_new_version_keeps_identity_and_merges_params():
    v1 = StrategySpec.create("Bold", "combined", {"threshold": 80})
    v2 = v1.new_version(params={"logic": "and"}, description="Both conditions")
    assert v2.strategy_id == v1.strategy_id
    assert v2.strategy_version_id != v1.strategy_version_id
    assert v2.version == 2
    assert v2.params == {"threshold": 80, "max_throws": 4, "logic": "and"}
    assert v1.params["logic"] == "or"  # original untouched
    assert v2.label() == "Bold (v2)"


def test_new_version_validates_and_restricts_fields():
    v1 = StrategySpec.create("Bold", "threshold", {"threshold": 80})
    with pytest.raises(ValidationError):
        v1.new_version(params={"threshold": 0})
    with pytest.raises(ValueError, match="cannot change"):
        v1.new_version(type="random")


def test_specs_are_immutable():
    s = StrategySpec.create("Bold", "threshold")
    with pytest.raises(ValidationError):
        s.name = "Other"


def test_presets_cover_every_type_with_stable_ids():
    assert {p.type for p in PRESETS} == {t.name for t in list_types()}
    assert len({p.strategy_id for p in PRESETS}) == len(PRESETS)
    from ambiciosa.strategies import presets as again

    assert [p.strategy_version_id for p in again.PRESETS] == [p.strategy_version_id for p in PRESETS]
    for p in PRESETS:
        p.build()
