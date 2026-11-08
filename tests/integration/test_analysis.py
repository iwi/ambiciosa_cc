"""Phase 6 completion check: every metric shown in Analyse matches an independent calculation.

Each test reads the raw stored rows with plain SELECTs and recomputes the
metric in Python (statistics, fractions, explicit loops), sharing no code
with ambiciosa.analysis, then compares it with what the analysis returns.
"""

import math
import statistics
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import product

import pytest

from ambiciosa.analysis import chi2_sf_df5, compare_runs, exact_throw_distribution, nice_width, run_analysis, wilson
from ambiciosa.persistence import Database
from ambiciosa.simulation import SimulationConfig, SimulationRunner

approx = pytest.approx


@pytest.fixture(scope="module")
def db():
    d = Database(":memory:")
    yield d
    d.close()


def run(db, **cfg):
    base = dict(n_games=400, master_seed=99, workers=1)
    p = SimulationRunner(db).run(SimulationConfig.model_validate({**base, **cfg}))
    assert p.status == "completed", p.error
    return str(p.simulation_id)


@pytest.fixture(scope="module")
def runs(db):
    return {
        "multi": run(db, target=300, record_level="full",
                     players=["Stop at 30", "Coin flip 75%", {"name": "Bold", "strategy": {"type": "threshold", "params": {"threshold": 60}}}]),
        "single": run(db, target=1000, record_level="summary", players=["Stop at 30"]),
        "shared": run(db, target=60, end_rule="equal_turns", record_level="turns", players=["Stop at 30", "Stop at 50"]),
        "capped": run(db, target=1000, max_turns=15, record_level="summary", players=["Stop at 30", "Stop at 50"]),
        "loaded": run(db, n_games=150, target=300, record_level="full", face_weights=[1, 1, 1, 1, 2, 3],
                      players=["Stop at 50"]),
    }


def raw_players(db, sid):
    rows = db.conn.execute(
        "SELECT gp.game_id, gp.seat, gp.play_order, gp.final_score, gp.is_winner, gp.turns_taken, "
        "gp.total_throws, gp.busts FROM game_player gp, game g WHERE gp.game_id = g.game_id AND g.simulation_id = ?",
        [sid]).fetchall()
    keys = ("game_id", "seat", "play_order", "final_score", "is_winner", "turns_taken", "total_throws", "busts")
    return [dict(zip(keys, r)) for r in rows]


def win_shares(rows):
    winners = Counter(r["game_id"] for r in rows if r["is_winner"])
    return [Fraction(1, winners[r["game_id"]]) if r["is_winner"] else Fraction(0) for r in rows]


def wilson_independent(k, n, z=1.959963984540054):
    # Wilson (1927), written out from the textbook formula.
    p = k / n
    a = p + z ** 2 / (2 * n)
    b = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    c = 1 + z ** 2 / n
    return (a - b) / c, (a + b) / c


# ------------------------------------------------------------ spec 3.3 list


@pytest.mark.parametrize("name", ["multi", "single", "shared", "capped", "loaded"])
def test_player_metrics_match_independent_calculation(db, runs, name):
    sid = runs[name]
    analysis = run_analysis(db, sid)
    target = analysis["simulation"]["target"]
    rows = raw_players(db, sid)
    shares = win_shares(rows)
    by_seat = defaultdict(list)
    for r, s in zip(rows, shares, strict=True):
        by_seat[r["seat"]].append((r, s))

    assert len(analysis["players"]) == len(by_seat)
    for m in analysis["players"]:
        mine = by_seat[m["seat"]]
        n = len(mine)
        wins = sum(s for _, s in mine)
        assert m["games"] == n
        # Win percentage for each strategy
        assert m["wins"] == approx(float(wins))
        assert m["win_rate"] == approx(float(wins / n))
        lo, hi = wilson_independent(float(wins), n)
        assert (m["win_rate_low"], m["win_rate_high"]) == (approx(max(lo, 0)), approx(min(hi, 1)))
        # Turns required to reach the target: mean, median, min, max, standard deviation
        reached = [r["turns_taken"] for r, _ in mine if r["final_score"] >= target]
        assert m["reached_target"] == len(reached)
        if reached:
            assert m["turns_to_target_mean"] == approx(statistics.fmean(reached))
            assert m["turns_to_target_median"] == approx(statistics.median(reached))
            assert m["turns_to_target_min"] == min(reached)
            assert m["turns_to_target_max"] == max(reached)
            sd = statistics.stdev(reached) if len(reached) > 1 else None
            assert m["turns_to_target_sd"] == (approx(sd) if sd is not None else None)
        else:
            assert m["turns_to_target_mean"] is None and m["turns_to_target_min"] is None
        # Average points per turn and throws per turn (ratios of totals)
        turns = sum(r["turns_taken"] for r, _ in mine)
        assert m["points_per_turn"] == approx(sum(r["final_score"] for r, _ in mine) / turns)
        assert m["throws_per_turn"] == approx(sum(r["total_throws"] for r, _ in mine) / turns)
        assert m["bust_rate"] == approx(sum(r["busts"] for r, _ in mine) / turns)
        assert m["mean_final_score"] == approx(statistics.fmean(r["final_score"] for r, _ in mine))

    # Number of games simulated
    assert analysis["overview"]["games"] == len({r["game_id"] for r in rows})
    assert analysis["simulation"]["n_games_completed"] == analysis["overview"]["games"]


def test_shared_wins_are_split(db, runs):
    analysis = run_analysis(db, runs["shared"])
    rows = raw_players(db, runs["shared"])
    shared_games = {g for g, c in Counter(r["game_id"] for r in rows if r["is_winner"]).items() if c > 1}
    assert shared_games, "the tiny target should produce shared wins"
    assert analysis["overview"]["shared_wins"] == len(shared_games)
    assert sum(p["wins"] for p in analysis["players"]) == approx(analysis["overview"]["games"])


def test_capped_games_have_no_winner_and_no_turns_to_target(db, runs):
    a = run_analysis(db, runs["capped"])
    assert a["overview"]["unfinished"] == a["overview"]["games"]
    assert all(p["win_rate"] == 0 for p in a["players"])


def test_configuration_and_strategy_parameters_are_reported(db, runs):
    a = run_analysis(db, runs["multi"])["simulation"]
    assert (a["target"], a["end_rule"], a["record_level"], a["master_seed"]) == (300, "first_to_target", "full", 99)
    assert a["n_games_requested"] == a["n_games_completed"] == 400
    assert [s["name"] for s in a["players"]] == ["Stop at 30", "Coin flip 75%", "Bold"]
    assert a["players"][2]["strategy"]["params"] == {"threshold": 60}
    assert a["players"][1]["strategy"]["params"] == {"p_continue": 0.75}
    assert run_analysis(db, runs["single"])["simulation"]["single_player"] is True
    assert run_analysis(db, runs["loaded"])["simulation"]["face_weights"] == approx([1 / 9] * 4 + [2 / 9, 3 / 9])


# --------------------------------------------------------------- positions


def test_win_rate_by_play_position(db, runs):
    sid = runs["multi"]
    rows = raw_players(db, sid)
    shares = win_shares(rows)
    a = run_analysis(db, sid)["play_position"]["rows"]
    cells = defaultdict(lambda: [0, Fraction(0)])
    overall = defaultdict(lambda: [0, Fraction(0)])
    for r, s in zip(rows, shares, strict=True):
        cells[(r["seat"], r["play_order"] + 1)][0] += 1
        cells[(r["seat"], r["play_order"] + 1)][1] += s
        overall[r["play_order"] + 1][0] += 1
        overall[r["play_order"] + 1][1] += s
    for row in a:
        n, w = (cells[(row["seat"], row["position"])] if row["seat"] is not None else overall[row["position"]])
        assert (row["games"], row["win_rate"]) == (n, approx(float(w / n)))
    assert {row["position"] for row in a if row["seat"] is None} == {1, 2, 3}


# ----------------------------------------------------------- distributions


def check_histogram(hist, values_by_key):
    width, starts = hist["bin_width"], hist["bin_start"]
    assert all(b - a == width for a, b in zip(starts, starts[1:], strict=False))
    for series in hist["series"]:
        values = values_by_key[series["seat"]]
        expected = [0] * len(starts)
        for v in values:
            expected[(v - starts[0]) // width] += 1
        assert series["counts"] == expected
        assert series["total"] == len(values)
        assert sum(series["shares"]) == approx(1.0)
    assert len(hist["series"]) == len(values_by_key)


def test_distributions_match_raw_rows(db, runs):
    sid = runs["multi"]
    a = run_analysis(db, sid)
    target = a["simulation"]["target"]
    rows = raw_players(db, sid)
    by_seat_reached, by_seat_final = defaultdict(list), defaultdict(list)
    for r in rows:
        by_seat_final[r["seat"]].append(r["final_score"])
        if r["final_score"] >= target:
            by_seat_reached[r["seat"]].append(r["turns_taken"])
    check_histogram(a["distributions"]["turns_to_target"], by_seat_reached)
    check_histogram(a["distributions"]["final_score"], by_seat_final)
    rounds = [r[0] for r in db.conn.execute("SELECT n_rounds FROM game WHERE simulation_id = ?", [sid]).fetchall()]
    check_histogram(a["distributions"]["game_length"], {None: rounds})


def test_turn_level_metrics(db, runs):
    for name in ("multi", "shared"):
        sid = runs[name]
        a = run_analysis(db, sid)
        turns = db.conn.execute(
            "SELECT t.seat, t.end_reason::VARCHAR, t.turn_score, t.n_throws FROM turn t, game g "
            "WHERE t.game_id = g.game_id AND g.simulation_id = ?", [sid]).fetchall()
        by_seat = defaultdict(list)
        for seat, reason, score, n in turns:
            by_seat[seat].append((reason, score, n))
        for row in a["turns"]["end_reasons"]:
            mine = by_seat[row["seat"]]
            reasons = Counter(r for r, _, _ in mine)
            assert row["turns"] == len(mine)
            for key in ("stop", "reached_target", "bust_zero", "bust_negative"):
                assert row[key] == approx(reasons[key] / len(mine))
            assert row["mean_turn_score"] == approx(statistics.fmean(s for _, s, _ in mine))
            banked = [s for r, s, _ in mine if r in ("stop", "reached_target")]
            assert row["mean_banked_score"] == approx(statistics.fmean(banked))
            assert row["mean_throws"] == approx(statistics.fmean(n for _, _, n in mine))
        check_histogram(a["turns"]["turn_score"], {s: [v for _, v, _ in t] for s, t in by_seat.items()})
        check_histogram(a["turns"]["throws_per_turn"], {s: [v for _, _, v in t] for s, t in by_seat.items()})
        # The turn table and the player totals agree.
        players = {p["seat"]: p for p in a["players"]}
        for seat, mine in by_seat.items():
            assert players[seat]["turns"] == len(mine)
            assert players[seat]["throws"] == sum(n for _, _, n in mine)


def test_summary_runs_have_no_turn_or_throw_sections(db, runs):
    a = run_analysis(db, runs["single"])
    assert a["available"] == {"turns": False, "throws": False}
    assert a["turns"] is None and a["throws"] is None


# ---------------------------------------------------------------- throws


def exact_fair():
    """The exact throw-score distribution for fair dice, by brute force over 216 ordered throws."""
    def score(d):
        if d[0] == d[1] == d[2]:
            return {5: 100, 4: 50, 1: -100, 0: -300}.get(d[0], 0)
        return 10 * d.count(5) + 5 * d.count(4)
    c = Counter(score(d) for d in product(range(6), repeat=3))
    return {s: Fraction(n, 216) for s, n in c.items()}


def test_exact_throw_distribution():
    fair = exact_fair()
    ours = exact_throw_distribution(None)
    assert set(ours) == set(fair)
    for s, p in fair.items():
        assert ours[s] == approx(float(p))
    assert sum(p for s, p in fair.items() if s == 0) == Fraction(62, 216)       # the spec-level fact
    assert sum(p for s, p in fair.items() if s < 0) == Fraction(2, 216)
    loaded = exact_throw_distribution((0, 0, 0, 0, 0, 1))                         # only Aces
    assert loaded == {100: approx(1.0)} or loaded[100] == approx(1.0)


@pytest.mark.parametrize("name", ["multi", "loaded"])
def test_throw_level_metrics(db, runs, name):
    sid = runs[name]
    a = run_analysis(db, sid)
    weights = a["simulation"]["face_weights"] or [1 / 6] * 6
    throws = db.conn.execute(
        "SELECT x.die1, x.die2, x.die3, x.throw_score FROM throw x, game g "
        "WHERE x.game_id = g.game_id AND g.simulation_id = ?", [sid]).fetchall()
    th = a["throws"]
    assert th["n_throws"] == len(throws)
    faces = Counter(d for t in throws for d in t[:3])
    total = 3 * len(throws)
    for f in th["faces"]:
        assert f["count"] == faces[f["code"]]
        assert f["share"] == approx(faces[f["code"]] / total)
        assert f["expected_share"] == approx(weights[f["code"]])
    chi2 = sum((faces[i] - total * weights[i]) ** 2 / (total * weights[i]) for i in range(6))
    assert th["face_test"]["chi2"] == approx(chi2)
    scores = Counter(t[3] for t in throws)
    for s in th["scores"]:
        assert s["count"] == scores[s["score"]]
    assert th["mean_score"]["observed"] == approx(statistics.fmean(t[3] for t in throws))
    assert th["turn_ending_rate"]["observed"] == approx(sum(1 for t in throws if t[3] <= 0) / len(throws))
    # The observed values sit where the exact probabilities say they should (fixed seed, so not flaky).
    ms = th["mean_score"]
    assert abs(ms["observed"] - ms["expected"]) < 4 * ms["standard_error"]
    if name == "multi":
        assert th["mean_score"]["expected"] == approx(float(sum(s * p for s, p in exact_fair().items())))
        assert th["turn_ending_rate"]["expected"] == approx(64 / 216)
        assert th["face_test"]["p_value"] > 0.001


# ------------------------------------------------------------ comparisons


def test_strategy_matrix_never_pools_runs(db, runs):
    c = compare_runs(db, [runs["multi"], runs["shared"], runs["single"]])
    assert [r["simulation"]["simulation_id"] for r in c["runs"]] == [runs["multi"], runs["shared"], runs["single"]]
    stop30 = next(s for s in c["strategies"] if s["strategy_name"] == "Stop at 30")
    assert set(stop30["cells"]) == {runs["multi"], runs["shared"], runs["single"]}
    for sid, cell in stop30["cells"].items():
        seat_rows = [r for r, s in zip(raw_players(db, sid), win_shares(raw_players(db, sid)), strict=True)]
        a = run_analysis(db, sid)
        expected = next(p for p in a["players"] if p["strategy_name"] == "Stop at 30")
        assert cell["games"] == expected["games"]
        assert cell["win_rate"] == approx(expected["win_rate"])
        assert cell["points_per_turn"] == approx(expected["points_per_turn"])
        reached = [r["turns_taken"] for r in raw_players(db, sid)
                   if r["seat"] == expected["seat"] and r["final_score"] >= a["simulation"]["target"]]
        assert cell["turns_to_target_mean"] == (approx(statistics.fmean(reached)) if reached else None)
        assert seat_rows
    bold = next(s for s in c["strategies"] if s["strategy_name"] == "threshold (threshold=60)")
    assert set(bold["cells"]) == {runs["multi"]}


def test_same_strategy_in_two_seats_is_combined_within_a_run(db):
    sid = run(db, n_games=100, target=200, record_level="summary", players=["Stop at 30", "Stop at 30"])
    c = compare_runs(db, [sid])
    (row,) = c["strategies"]
    cell = row["cells"][sid]
    assert cell["games"] == 200 and cell["seats"] == [0, 1]
    assert cell["win_rate"] == approx(0.5)            # one of the two seats wins every game


# ------------------------------------------------------------------ helpers


def test_wilson_reference_values():
    lo, hi = wilson(50, 100)
    assert (lo, hi) == (approx(0.4038, abs=1e-4), approx(0.5962, abs=1e-4))
    lo, hi = wilson(0, 10)
    assert lo == 0 and hi == approx(0.2775, abs=1e-4)
    assert wilson(10, 10)[1] == 1.0
    assert wilson(1, 0) is None


def test_chi2_df5_reference_values():
    assert chi2_sf_df5(11.0705) == approx(0.05, abs=1e-4)     # the 5% critical value
    assert chi2_sf_df5(15.0863) == approx(0.01, abs=1e-4)
    assert chi2_sf_df5(4.3515) == approx(0.5, abs=1e-4)       # the median
    assert chi2_sf_df5(0) == 1.0


@pytest.mark.parametrize("span, base, expected", [(10, 1, 1), (61, 1, 2), (130, 1, 5), (1300, 5, 50), (0, 5, 5), (59, 5, 5)])
def test_nice_width(span, base, expected):
    assert nice_width(span, base=base) == expected


# ------------------------------------------------- configurable scoring (decision 11)


def test_custom_scoring_run_is_stored_and_analysed_with_its_own_scores(db):
    values = dict(ace=20, king=-5, three_aces=300, three_kings=0, three_tens=25, three_nines=-50)
    sid = run(db, n_games=120, target=400, record_level="full", scoring=values, players=["Stop at 30", "Stop at 50"])
    a = run_analysis(db, sid)
    assert a["simulation"]["scoring"] == values and a["simulation"]["scoring_is_default"] is False

    # Every stored throw scores what the custom rules say (independent rules text).
    def score(d):
        if d[0] == d[1] == d[2] and d[0] in (5, 4, 1, 0):
            return {5: values["three_aces"], 4: values["three_kings"], 1: values["three_tens"], 0: values["three_nines"]}[d[0]]
        return values["ace"] * d.count(5) + values["king"] * d.count(4)

    throws = db.conn.execute("SELECT x.die1, x.die2, x.die3, x.throw_score FROM throw x, game g "
                             "WHERE x.game_id = g.game_id AND g.simulation_id = ?", [sid]).fetchall()
    assert throws and all(score(t[:3]) == t[3] for t in throws)

    # The exact distribution is the custom one, by brute force with exact fractions.
    exact = Counter(score(d) for d in product(range(6), repeat=3))
    shown = {s["score"]: s["expected_share"] for s in a["throws"]["scores"]}
    assert set(shown) == set(exact)
    for s, n in exact.items():
        assert shown[s] == approx(n / 216)
    assert a["throws"]["mean_score"]["expected"] == approx(float(sum(Fraction(s * n, 216) for s, n in exact.items())))
    assert a["throws"]["turn_ending_rate"]["expected"] == approx(sum(n for s, n in exact.items() if s <= 0) / 216)
    assert [f["face"] for f in a["throws"]["faces"]] == ["9", "10", "J", "Q", "K", "A"]


def test_runs_stored_without_scoring_use_the_defaults(db, runs):
    a = run_analysis(db, runs["multi"])
    assert a["simulation"]["scoring_is_default"] is True
    shown = {r["score"]: r["expected_share"] for r in a["throws"]["scores"]}
    assert shown == approx({s: float(p) for s, p in exact_fair().items()})
