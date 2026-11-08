"""Scoring tests: every one of the 216 ordered throws, plus the specials."""

from collections import Counter
from fractions import Fraction
from itertools import permutations, product

import pytest

from ambiciosa.engine import SCORE_TABLE, Face, score_throw
from ambiciosa.engine.dice import parse_throw

ALL_THROWS = [tuple(Face(c) for c in codes) for codes in product(range(6), repeat=3)]


def reference_score(throw) -> int:
    """Independent implementation of spec 2.2, written from the rules text."""
    counts = Counter(throw)
    if counts[Face.ACE] == 3:
        return 100
    if counts[Face.KING] == 3:
        return 50
    if counts[Face.TEN] == 3:
        return -100
    if counts[Face.NINE] == 3:
        return -300
    return 10 * counts[Face.ACE] + 5 * counts[Face.KING]


def test_table_covers_all_216_throws():
    assert len(ALL_THROWS) == 216
    assert len(SCORE_TABLE) == 216


@pytest.mark.parametrize("throw", ALL_THROWS, ids=lambda t: "".join(f.symbol for f in t))
def test_every_throw_matches_reference(throw):
    assert score_throw(throw) == reference_score(throw)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("AAA", 100),   # special, not 30
        ("KKK", 50),    # special, not 15
        ("TTT", -100),
        ("999", -300),
        ("JJJ", 0),     # decision 4
        ("QQQ", 0),     # decision 4
        ("AAK", 25),
        ("AKK", 20),
        ("A9T", 10),
        ("K9J", 5),
        ("AA9", 20),
        ("KKT", 10),
        ("99A", 10),    # a pair of nines is not special
        ("TTK", 5),
        ("99 T", 0),
        ("JQT", 0),
        ("AKQ", 15),
    ],
)
def test_named_combinations(text, expected):
    assert score_throw(parse_throw(text)) == expected


@pytest.mark.parametrize("throw", ALL_THROWS[::7])
def test_order_does_not_matter(throw):
    scores = {score_throw(p) for p in permutations(throw)}
    assert len(scores) == 1


def test_outcome_counts_with_fair_dice():
    scores = [score_throw(t) for t in ALL_THROWS]
    assert sum(s == 0 for s in scores) == 62     # no Ace/King, minus 999 and TTT
    assert sum(s < 0 for s in scores) == 2
    assert sum(s > 0 for s in scores) == 152
    assert Counter(s for s in scores if s < 0) == {-100: 1, -300: 1}


def test_exact_mean_throw_score():
    # Per-die expectation 7.5 per throw, minus the special adjustments:
    # AAA 100 instead of 30 (+70), KKK 50 instead of 15 (+35), TTT -100, 999 -300.
    mean = Fraction(sum(score_throw(t) for t in ALL_THROWS), 216)
    assert mean == Fraction(7, 1) + Fraction(1, 2) + Fraction(70 + 35 - 100 - 300, 216)
    assert float(mean) == pytest.approx(6.1343, abs=1e-4)


def test_face_symbols_round_trip():
    for face in Face:
        assert Face.from_symbol(face.symbol) is face
    assert [f.symbol for f in Face] == ["9", "10", "J", "Q", "K", "A"]      # decision 12
    with pytest.raises(ValueError):
        Face.from_symbol("X")
    with pytest.raises(ValueError):
        Face.from_symbol("7")                                              # the old faces are gone
    with pytest.raises(ValueError):
        parse_throw("AA")


@pytest.mark.parametrize("text", ["9TA", "9 10 A", "910A", "9 T A", "9t a"])
def test_ten_can_be_written_10_or_t(text):
    assert parse_throw(text) == (Face.NINE, Face.TEN, Face.ACE)


def test_parse_rejects_wrong_dice_counts():
    for bad in ("1010", "9T", "AAAA", "10 10 10 10"):
        with pytest.raises(ValueError):
            parse_throw(bad)
