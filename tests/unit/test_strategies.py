"""Strategy decisions against hand-built game states."""

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from ambiciosa.engine import Decision, DecisionContext
from ambiciosa.strategies import (
    CombinedParams,
    CombinedStrategy,
    GameStateParams,
    GameStateStrategy,
    MaxThrowsParams,
    MaxThrowsStrategy,
    RandomParams,
    RandomStrategy,
    ThresholdParams,
    ThresholdStrategy,
    get_type,
    list_types,
)

C, S = Decision.CONTINUE, Decision.STOP
RNG = np.random.default_rng(0)


def ctx(**kw) -> DecisionContext:
    base = dict(
        turn_points=20,
        throws_this_turn=1,
        last_throw_score=20,
        my_score=300,
        best_opponent_score=250,
        gap_to_leader=50,
        points_to_target=700,
        num_opponents=2,
        is_leading=True,
        turn_number=10,
        target=1000,
    )
    base.update(kw)
    return DecisionContext(**base)


# ------------------------------------------------------------- 1. threshold


@pytest.mark.parametrize("points, expected", [(5, C), (49, C), (50, S), (51, S), (300, S)])
def test_threshold_boundary(points, expected):
    s = ThresholdStrategy(ThresholdParams(threshold=50))
    result = s.decide(ctx(turn_points=points), RNG)
    assert result.decision is expected
    assert str(points) in result.reason and "50" in result.reason


def test_threshold_ignores_game_situation():
    s = ThresholdStrategy(ThresholdParams(threshold=30))
    for situation in (dict(is_leading=False, gap_to_leader=-500), dict(points_to_target=10)):
        assert s.decide(ctx(turn_points=25, **situation), RNG).decision is C


# ------------------------------------------------------------ 2. max throws


@pytest.mark.parametrize("throws, expected", [(1, C), (3, C), (4, S), (5, S)])
def test_max_throws_boundary(throws, expected):
    s = MaxThrowsStrategy(MaxThrowsParams(max_throws=4))
    assert s.decide(ctx(throws_this_turn=throws), RNG).decision is expected


def test_max_throws_of_one_always_stops():
    s = MaxThrowsStrategy(MaxThrowsParams(max_throws=1))
    assert s.decide(ctx(throws_this_turn=1, turn_points=5), RNG).decision is S


# -------------------------------------------------------------- 3. combined


@pytest.mark.parametrize(
    "logic, points, throws, expected",
    [
        ("or", 49, 3, C),
        ("or", 50, 3, S),
        ("or", 49, 4, S),
        ("or", 50, 4, S),
        ("and", 49, 3, C),
        ("and", 50, 3, C),
        ("and", 49, 4, C),
        ("and", 50, 4, S),
    ],
)
def test_combined_truth_table(logic, points, throws, expected):
    s = CombinedStrategy(CombinedParams(threshold=50, max_throws=4, logic=logic))
    result = s.decide(ctx(turn_points=points, throws_this_turn=throws), RNG)
    assert result.decision is expected
    assert logic.upper() in result.reason


# ---------------------------------------------------------------- 4. random


@pytest.mark.parametrize("p, expected", [(0.0, S), (1.0, C)])
def test_random_extremes_are_deterministic(p, expected):
    s = RandomStrategy(RandomParams(p_continue=p))
    rng = np.random.default_rng(1)
    assert {s.decide(ctx(), rng).decision for _ in range(500)} == {expected}


@pytest.mark.statistical
@pytest.mark.parametrize("p", [0.25, 0.75])
def test_random_frequency_matches_probability(p):
    s = RandomStrategy(RandomParams(p_continue=p))
    rng = np.random.default_rng(2026)
    n = 100_000
    share = sum(s.decide(ctx(), rng).decision is C for _ in range(n)) / n
    assert share == pytest.approx(p, abs=5 * np.sqrt(p * (1 - p) / n))


def test_random_is_reproducible_from_its_stream():
    s = RandomStrategy(RandomParams(p_continue=0.5))
    r1, r2 = np.random.default_rng(9), np.random.default_rng(9)
    assert [s.decide(ctx(), r1).decision for _ in range(100)] == [
        s.decide(ctx(), r2).decision for _ in range(100)
    ]


# ------------------------------------------------------------ 5. game state

GS = GameStateStrategy(
    GameStateParams(leading_threshold=30, trailing_threshold=60, close_to_win_points=100, close_threshold=None)
)


def test_leading_uses_conservative_threshold():
    leading = ctx(is_leading=True, gap_to_leader=50)
    assert GS.decide(replace(leading, turn_points=25), RNG).decision is C
    r = GS.decide(replace(leading, turn_points=30), RNG)
    assert r.decision is S and r.reason.startswith("leading by 50")


def test_trailing_uses_aggressive_threshold():
    trailing = ctx(is_leading=False, my_score=200, best_opponent_score=500, gap_to_leader=-300, points_to_target=800)
    assert GS.decide(replace(trailing, turn_points=55), RNG).decision is C
    r = GS.decide(replace(trailing, turn_points=60), RNG)
    assert r.decision is S and r.reason.startswith("trailing by 300")


def test_tie_is_not_ahead_and_uses_trailing_threshold():
    tied = ctx(is_leading=False, my_score=400, best_opponent_score=400, gap_to_leader=0, points_to_target=600)
    r = GS.decide(replace(tied, turn_points=40), RNG)
    assert r.decision is C and r.reason.startswith("tied for the lead")


def test_single_player_uses_leading_threshold():
    alone = ctx(best_opponent_score=None, num_opponents=0, gap_to_leader=0, is_leading=True)
    r = GS.decide(replace(alone, turn_points=30), RNG)
    assert r.decision is S and r.reason.startswith("playing alone")


@pytest.mark.parametrize("needed, expected", [(100, C), (60, C), (101, S)])
def test_close_to_win_goes_for_the_win(needed, expected):
    # turn total 40 would stop under the leading threshold (30), but close to winning we keep going
    c = ctx(turn_points=40, my_score=1000 - needed, points_to_target=needed, is_leading=True)
    assert GS.decide(c, RNG).decision is expected


def test_close_to_win_takes_precedence_over_trailing():
    c = ctx(turn_points=70, is_leading=False, gap_to_leader=-20, points_to_target=90)
    assert GS.decide(c, RNG).decision is C


def test_close_threshold_when_set():
    s = GameStateStrategy(GameStateParams(close_to_win_points=200, close_threshold=15))
    c = ctx(points_to_target=150)
    assert s.decide(replace(c, turn_points=10), RNG).decision is C
    r = s.decide(replace(c, turn_points=15), RNG)
    assert r.decision is S and r.reason.startswith("close to winning (150 needed)")


def test_close_rule_can_be_disabled():
    s = GameStateStrategy(GameStateParams(leading_threshold=30, close_to_win_points=None))
    assert s.decide(ctx(turn_points=35, points_to_target=40), RNG).decision is S


# ------------------------------------------------------------- registry


def test_all_five_types_registered_with_schemas():
    names = [t.name for t in list_types()]
    assert names == ["threshold", "max_throws", "combined", "random", "game_state"]
    for t in list_types():
        schema = t.json_schema()
        assert schema["type"] == "object" and schema["properties"]
        assert t.title and t.description
        t.factory(t.params_model())  # defaults are valid


@pytest.mark.parametrize(
    "type_name, params",
    [
        ("threshold", {"threshold": 0}),
        ("max_throws", {"max_throws": 0}),
        ("combined", {"logic": "xor"}),
        ("random", {"p_continue": 1.5}),
        ("threshold", {"threshold": 50, "extra": 1}),
        ("game_state", {"close_threshold": 0}),
    ],
)
def test_invalid_params_rejected(type_name, params):
    with pytest.raises(ValidationError):
        get_type(type_name).validate(params)


def test_unknown_type_rejected():
    with pytest.raises(ValueError, match="unknown strategy type"):
        get_type("magic")


def test_duplicate_registration_rejected():
    from ambiciosa.strategies import register

    with pytest.raises(ValueError, match="already registered"):
        register(get_type("threshold"))


def test_validate_accepts_an_existing_params_instance():
    p = ThresholdParams(threshold=40)
    assert get_type("threshold").validate(p) is p
