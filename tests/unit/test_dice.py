import numpy as np
import pytest

from ambiciosa.engine import Face, RandomDice, ScriptedDice, normalise_weights


def test_scripted_dice_returns_throws_in_order_then_raises():
    dice = ScriptedDice(["AAK", "999"])
    assert dice.roll() == (Face.ACE, Face.ACE, Face.KING)
    assert dice.roll() == (Face.NINE,) * 3
    assert dice.remaining == 0
    with pytest.raises(RuntimeError, match="exhausted"):
        dice.roll()


def test_random_dice_is_reproducible():
    a = RandomDice(123)
    b = RandomDice(123)
    assert [a.roll() for _ in range(200)] == [b.roll() for _ in range(200)]
    x, y = RandomDice(123), RandomDice(124)
    assert [x.roll() for _ in range(50)] != [y.roll() for _ in range(50)]


def test_weights_are_normalised_and_validated():
    assert normalise_weights(None) == pytest.approx((1 / 6,) * 6)
    assert normalise_weights([2, 2, 2, 2, 1, 1]) == pytest.approx((0.2, 0.2, 0.2, 0.2, 0.1, 0.1))
    for bad in ([1] * 5, [1, 1, 1, 1, 1, -1], [0] * 6, [1, 1, 1, 1, 1, float("nan")]):
        with pytest.raises(ValueError):
            normalise_weights(bad)


def test_zero_weight_face_never_appears():
    dice = RandomDice(7, weights=[1, 1, 1, 1, 1, 0])  # no Aces
    faces = {f for _ in range(2000) for f in dice.roll()}
    assert Face.ACE not in faces
    assert len(faces) == 5


@pytest.mark.statistical
@pytest.mark.parametrize("weights", [None, [3, 1, 1, 1, 1, 3]])
def test_face_frequencies_match_weights(weights):
    dice = RandomDice(2026, weights=weights)
    n = 60_000
    counts = np.zeros(6)
    for _ in range(n // 3):
        for f in dice.roll():
            counts[f] += 1
    p = np.array(normalise_weights(weights))
    expected = p * n
    # Each face within 5 standard errors of its expected count.
    sd = np.sqrt(n * p * (1 - p))
    assert np.all(np.abs(counts - expected) < 5 * sd)
