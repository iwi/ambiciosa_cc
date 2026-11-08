"""Complete random games: reproducibility, invariants and long-run statistics."""

import numpy as np
import pytest

from ambiciosa.engine import (
    Decision,
    DecisionResult,
    EndRule,
    Game,
    GameConfig,
    GameStatus,
    PlayerConfig,
    TurnEndReason,
)


def stop_at(threshold):
    def decide(seat, ctx):
        if ctx.turn_points >= threshold:
            return DecisionResult(Decision.STOP, f"turn total {ctx.turn_points} >= {threshold}")
        return Decision.CONTINUE

    return decide


def players(n):
    return tuple(PlayerConfig(f"Bot {i}") for i in range(n))


def run(seed, n=3, **kw):
    g = Game(GameConfig(players=players(n), **kw), seed=seed)
    g.play_to_end(stop_at(40))
    return g


def summary(g):
    return (
        g.play_order,
        g.winners,
        g.status,
        g.scores(),
        [(t.seat, [th.dice for th in t.throws], t.turn_score) for t in g.history],
    )


def test_same_seed_same_game():
    assert summary(run(42)) == summary(run(42))


def test_different_seeds_differ():
    assert summary(run(1)) != summary(run(2))


def test_play_order_is_randomised_and_reproducible():
    orders = {Game(GameConfig(players=players(4)), seed=s).play_order for s in range(50)}
    assert len(orders) > 10
    assert all(sorted(o) == [0, 1, 2, 3] for o in orders)


@pytest.mark.parametrize("seed", range(30))
@pytest.mark.parametrize("rule", list(EndRule))
def test_invariants_hold_in_random_games(seed, rule):
    g = run(seed, n=4, end_rule=rule)
    assert g.status is GameStatus.FINISHED
    # banked scores equal the sum of turn scores
    for p in g.players:
        assert p.score == sum(t.turn_score for t in g.history if t.seat == p.seat)
        assert p.turns_taken == sum(1 for t in g.history if t.seat == p.seat)
    for t in g.history:
        last = t.throws[-1]
        if t.end_reason is TurnEndReason.STOP:
            assert last.decision is Decision.STOP and t.turn_score == t.points > 0
        elif t.end_reason in (TurnEndReason.BUST_ZERO, TurnEndReason.BUST_NEGATIVE):
            assert t.turn_score == last.score <= 0 and last.decision is None
        else:
            assert t.end_reason is TurnEndReason.REACHED_TARGET and last.decision is None
        assert all(th.decision is Decision.CONTINUE for th in t.throws[:-1])
    top = max(g.scores())
    assert top >= 1000
    if rule is EndRule.FIRST_TO_TARGET:
        assert len(g.winners) == 1 and g.players[g.winner].reached_target
        assert sum(p.reached_target for p in g.players) == 1
    else:
        turns = [p.turns_taken for p in g.players]
        assert len(set(turns)) == 1  # everyone had the same number of turns
        assert all(g.players[w].score == top for w in g.winners)


def test_always_continue_never_finishes():
    g = Game(GameConfig(players=players(1), max_turns=200), seed=5)
    g.play_to_end(lambda seat, ctx: Decision.CONTINUE)
    assert g.status is GameStatus.UNFINISHED
    assert g.players[0].turns_taken == 200
    assert g.players[0].score <= 0


@pytest.mark.statistical
def test_bust_rate_matches_exact_probability():
    g = Game(GameConfig(players=players(1), max_turns=20_000, target=10**9), seed=99)
    g.play_to_end(lambda seat, ctx: Decision.STOP)  # one throw per turn
    first_throws = [t.throws[0].score for t in g.history]
    n = len(first_throws)
    zero = np.mean([s == 0 for s in first_throws])
    neg = np.mean([s < 0 for s in first_throws])
    assert n == 20_000
    assert zero == pytest.approx(62 / 216, abs=5 * np.sqrt(0.287 * 0.713 / n))
    assert neg == pytest.approx(2 / 216, abs=5 * np.sqrt(0.0093 * 0.9907 / n) + 1e-3)
