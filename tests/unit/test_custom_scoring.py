"""Configurable scoring (decision 11) and the 9 and 10 faces (decision 12)."""

from collections import Counter
from itertools import product

import pytest
from pydantic import ValidationError

from ambiciosa.engine import (
    DEFAULT_SCORING,
    Decision,
    Face,
    Game,
    GameConfig,
    PlayerConfig,
    Scoring,
    ScriptedDice,
    TurnEndReason,
    score_throw,
)
from ambiciosa.simulation import SimulationConfig
from ambiciosa.simulation.config import ScoringRules
from ambiciosa.strategies import PRESETS, play_automated

ALL_THROWS = [tuple(Face(c) for c in codes) for codes in product(range(6), repeat=3)]

CUSTOM = [
    dict(ace=20, king=10, three_aces=500, three_kings=250, three_tens=-50, three_nines=-1000),
    dict(ace=-5, king=0, three_aces=0, three_kings=-1, three_tens=40, three_nines=60),
    dict(ace=7, king=3, three_aces=15, three_kings=5, three_tens=0, three_nines=0),  # specials below 3 x per-die
    dict(ace=10_000, king=-10_000, three_aces=-10_000, three_kings=10_000, three_tens=1, three_nines=-1),
]


def reference(throw, s):
    """Independent rules text: specials first, then per Ace and per King, everything else 0."""
    c = Counter(throw)
    for face, key in ((Face.ACE, "three_aces"), (Face.KING, "three_kings"), (Face.TEN, "three_tens"),
                      (Face.NINE, "three_nines")):
        if c[face] == 3:
            return s[key]
    return s["ace"] * c[Face.ACE] + s["king"] * c[Face.KING]


@pytest.mark.parametrize("values", CUSTOM)
def test_every_throw_with_custom_scoring(values):
    scoring = Scoring(**values)
    for throw in ALL_THROWS:
        assert score_throw(throw, scoring) == reference(throw, values) == scoring.score(throw)


def test_defaults_are_the_spec_values():
    assert DEFAULT_SCORING.as_dict() == dict(ace=10, king=5, three_aces=100, three_kings=50,
                                             three_tens=-100, three_nines=-300)
    assert Scoring() == DEFAULT_SCORING and DEFAULT_SCORING.is_default
    assert not Scoring(ace=11).is_default
    assert Scoring.from_dict(None) is DEFAULT_SCORING and Scoring.from_dict({}) is DEFAULT_SCORING
    assert Scoring.from_dict({"ace": 20}) == Scoring(ace=20)


def test_specials_take_precedence_even_when_worth_less():
    s = Scoring(ace=50, three_aces=1)
    assert s.score((Face.ACE,) * 3) == 1
    assert s.score((Face.ACE, Face.ACE, Face.JACK)) == 100


def test_jacks_and_queens_stay_worth_nothing():
    s = Scoring(**CUSTOM[0])
    for throw in ((Face.JACK,) * 3, (Face.QUEEN,) * 3, (Face.JACK, Face.QUEEN, Face.NINE), (Face.TEN, Face.NINE, Face.NINE)):
        assert s.score(throw) == 0


@pytest.mark.parametrize("bad", [dict(ace=10_001), dict(three_nines=-10_001), dict(king=2.5), dict(ace="10"),
                                 dict(ace=True), dict(ace=None)])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(ValueError):
        Scoring(**bad)


def test_unknown_score_names_are_rejected():
    with pytest.raises(ValueError, match="unknown score names"):
        Scoring.from_dict({"three_sevens": -300})


def test_whole_number_floats_are_accepted():
    assert Scoring(ace=20.0).ace == 20


# ------------------------------------------------------------------ games


def one_player(scoring, throws, decide=Decision.CONTINUE):
    g = Game(GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), target=10_000, scoring=scoring),
             seed=0, dice=ScriptedDice(throws))
    return g


def test_a_negative_ace_ends_the_turn_with_that_score():
    g = one_player({"ace": -5}, ["KKJ", "AJQ"])
    g.throw()                                   # KKJ: 10, positive
    g.decide(Decision.CONTINUE)
    g.throw()                                   # AJQ: -5 -> the turn ends at -5
    turn = g.history[0]
    assert (turn.end_reason, turn.turn_score, g.players[0].score) == (TurnEndReason.BUST_NEGATIVE, -5, -5)


def test_zero_valued_aces_and_kings_end_the_turn():
    g = one_player(Scoring(ace=0, king=0), ["AKJ"])
    g.throw()
    assert g.history[0].end_reason is TurnEndReason.BUST_ZERO


def test_positive_three_nines_lets_the_player_continue():
    g = one_player(Scoring(three_nines=60), ["999"])
    rec = g.throw()
    assert rec.score == 60 and g.awaiting == "decision"


def test_game_config_accepts_a_mapping_and_rejects_nonsense():
    assert GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), scoring={"king": 6}).scoring == Scoring(king=6)
    with pytest.raises(ValueError):
        GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), scoring=42)


def test_scoring_does_not_change_the_dice():
    base = GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]), PlayerConfig("B", strategy=PRESETS[1])))
    other = GameConfig(players=base.players, scoring=Scoring(ace=25, king=12))
    a, b = play_automated(base, 5), play_automated(other, 5)
    assert a.play_order == b.play_order
    first_a, first_b = a.history[0].throws[0], b.history[0].throws[0]
    assert first_a.dice == first_b.dice
    assert first_a.score == score_throw(first_a.dice) and first_b.score == score_throw(first_b.dice, other.scoring)


# ---------------------------------------------------------------- configs


def test_simulation_config_scoring_defaults_partial_and_strict():
    c = SimulationConfig(n_games=1, players=["Stop at 30"])
    assert c.scoring == ScoringRules() and c.scoring.is_default
    c = SimulationConfig(n_games=1, players=["Stop at 30"], scoring={"ace": 15})
    assert c.scoring.ace == 15 and c.scoring.king == 5
    assert c.game_config().scoring == Scoring(ace=15)
    for bad in ({"ace": 10.5}, {"ace": "15"}, {"ace": 20_000}, {"seven": 1}):
        with pytest.raises(ValidationError):
            SimulationConfig(n_games=1, players=["Stop at 30"], scoring=bad)


def test_scoring_is_stored_and_restored():
    c = SimulationConfig(n_games=1, players=["Stop at 30"], scoring={"three_tens": -150})
    stored = c.stored_dict()
    assert stored["scoring"]["three_tens"] == -150
    specs = {str(s.strategy_version_id): s for s in c.strategies()}
    assert SimulationConfig.from_stored(stored, specs).scoring.three_tens == -150
    del stored["scoring"]                                # a run stored before decision 11
    assert SimulationConfig.from_stored(stored, specs).scoring.is_default


def test_scoring_from_yaml(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("n_games: 3\nplayers: [Stop at 30]\nscoring:\n  ace: 12\n  three_nines: -500\n")
    c = SimulationConfig.from_yaml(p)
    assert (c.scoring.ace, c.scoring.three_nines, c.scoring.king) == (12, -500, 5)


def test_scoring_rules_schema_has_titles_for_the_ui():
    props = ScoringRules.model_json_schema()["properties"]
    assert [props[k]["title"] for k in props] == ["Each Ace", "Each King", "Three Aces", "Three Kings", "Three 10s", "Three 9s"]
