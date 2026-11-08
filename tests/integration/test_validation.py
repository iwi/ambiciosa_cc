"""The exact single-player model, and simulated games against it."""

from fractions import Fraction

import pytest

from ambiciosa.engine.scoring import Scoring
from ambiciosa.simulation.cli import main
from ambiciosa.validation.exact import game_result, policy_for, throw_distribution, turn_result
from ambiciosa.validation.suite import CASES, Case, run_suite

approx = pytest.approx
FAIR = throw_distribution()


# --------------------------------------------- the model, on cases known by hand


def test_one_throw_turns_have_the_throw_distribution():
    tr = turn_result(policy_for("max_throws", {"max_throws": 1}, 1000), FAIR, 0, 1000)
    assert tr.expected_throws == approx(1.0) and tr.throws_sd == approx(0.0, abs=1e-9)
    assert tr.mean == approx(float(Fraction(7, 1) + Fraction(1, 2) + Fraction(70 + 35 - 100 - 300, 216)))
    assert tr.p_bust_zero == approx(62 / 216) and tr.p_bust_negative == approx(2 / 216)
    assert sum(tr.outcomes.values()) == approx(1.0)


def test_threshold_one_equals_one_throw():
    a = turn_result(policy_for("threshold", {"threshold": 1}, 1000), FAIR, 0, 1000)
    b = turn_result(policy_for("max_throws", {"max_throws": 1}, 1000), FAIR, 0, 1000)
    assert a.outcomes == approx(b.outcomes)


def test_two_throw_turn_by_hand():
    # Stop after two throws: the turn scores v1 + v2 if both positive, else the first non-positive throw.
    tr = turn_result(policy_for("max_throws", {"max_throws": 2}, 10**9), FAIR, 0, 10**9)
    pos = {v: p for v, p in FAIR.items() if v > 0}
    expected = {}
    for v, p in FAIR.items():
        if v <= 0:
            expected[v] = expected.get(v, 0) + p
    for v1, p1 in pos.items():
        for v2, p2 in FAIR.items():
            key = v1 + v2 if v2 > 0 else v2
            expected[key] = expected.get(key, 0) + p1 * p2
    assert tr.outcomes == approx(expected)
    p_pos = sum(pos.values())
    assert tr.expected_throws == approx(1 + p_pos)


def test_only_aces_reach_1000_in_exactly_ten_turns():
    only_aces = throw_distribution((0, 0, 0, 0, 0, 1))
    assert only_aces == {100: approx(1.0)}
    g = game_result(policy_for("threshold", {"threshold": 30}, 1000), only_aces, 1000, 500)
    assert g.p_turns[9] == approx(1.0) and g.p_unfinished == approx(0.0)
    assert (g.mean, g.median, g.sd) == (approx(10.0), 10, approx(0.0, abs=1e-9))


def test_reaching_the_target_ends_the_turn_mid_way():
    # Only Kings (+50 each), threshold 500: from 950 the first throw wins, so turn outcome is +50.
    only_kings = throw_distribution((0, 0, 0, 0, 1, 0))
    tr = turn_result(policy_for("threshold", {"threshold": 500}, 1000), only_kings, 950, 1000)
    assert tr.outcomes == {50: approx(1.0)} and tr.expected_throws == approx(1.0)


def test_never_scoring_never_finishes():
    only_jacks = throw_distribution((0, 0, 1, 0, 0, 0))
    g = game_result(policy_for("threshold", {"threshold": 30}, 1000), only_jacks, 1000, 40)
    assert g.p_unfinished == approx(1.0) and g.p_turns.sum() == approx(0.0)


def test_custom_scoring_enters_the_model():
    s = Scoring(ace=0, king=0, three_aces=1000, three_kings=0, three_tens=0, three_nines=0)
    d = throw_distribution(None, s)
    assert d == {0: approx(215 / 216), 1000: approx(1 / 216)}
    g = game_result(policy_for("threshold", {"threshold": 1}, 1000), d, 1000, 2000)
    # Each turn reaches the target with probability 1/216, independently: geometric, mean 216.
    assert g.mean == approx(216, rel=0.01)


def test_game_state_close_rule_only_near_the_target():
    pol = policy_for("game_state", {"leading_threshold": 30, "trailing_threshold": 60,
                                    "close_to_win_points": 100, "close_threshold": None}, 1000)
    assert pol(30, 2, 0) == 0.0 and pol(30, 2, 899) == 0.0      # 101 needed: threshold 30 applies
    assert pol(30, 2, 900) == 1.0                                # 100 needed: keep throwing
    assert pol.score_horizon == 100 and not pol.uses_throws


def test_unknown_strategy_type_has_no_model():
    with pytest.raises(ValueError):
        policy_for("neural_net", {}, 1000)


# ------------------------------------------------- simulated games against it


@pytest.mark.statistical
@pytest.mark.parametrize("case", [CASES[0], CASES[2], CASES[4], CASES[5], CASES[7], CASES[8]], ids=lambda c: c.name)
def test_simulation_matches_exact_results(case):
    (result,) = run_suite(n_games=1500, workers=1, master_seed=777, cases=(case,))
    failures = [(c.figure, c.exact, c.simulated, c.z) for c in result.checks if not c.passed]
    assert not failures, failures
    assert len(result.checks) >= 7


def test_a_wrong_engine_would_be_caught(monkeypatch):
    """The checks have power: tell the model a different score than the engine uses and it fails."""
    wrong = Case("Mismatch", "threshold", {"threshold": 30})
    import ambiciosa.validation.suite as suite

    real = suite.throw_distribution
    monkeypatch.setattr(suite, "throw_distribution",
                        lambda w, s: real(w, Scoring(ace=11)))       # the model believes Aces score 11
    (result,) = run_suite(n_games=1500, workers=1, master_seed=5, cases=(wrong,))
    assert not result.passed


def test_validate_command(tmp_path, capsys):
    report = tmp_path / "v.md"
    assert main(["validate", "--quick", "--games", "400", "--workers", "1", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "checks passed" in out
    text = report.read_text()
    assert text.startswith("# Validation report") and "Stop at 30" in text and "**FAIL**" not in text
