"""Exact results for single-player games, computed from the rules, not by simulation.

A single-player game is a Markov chain on the banked score. Within a turn, a
strategy that decides from the turn so far (turn points, throws made, and the
banked score) defines a second chain on (turn points, throws). Both chains
are small, so the exact distribution of every turn's outcome, and of the
number of turns needed to reach the target, can be computed directly.

This module shares no code with the engine or the strategies: it is written
from the rules text (spec 2.2-2.5, decisions 1, 3, 11) and the strategy
definitions (spec 4.2), so agreement between it and simulated games
validates the engine and the strategies together.

Only the throw-score distribution is reused, which is itself checked against
brute force over all 216 throws.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce

import numpy as np

from ..analysis.stats import exact_throw_distribution
from ..engine.scoring import DEFAULT_SCORING, Scoring

# A policy gives the probability of CONTINUING after a scoring throw, from
# (turn points, throws made this turn, banked score at the start of the turn).
Policy = Callable[[int, int, int], float]

PRUNE = 1e-16          # probability mass below this is dropped (and counted)


def policy_for(strategy_type: str, params: dict, target: int) -> Policy:
    """The single-player decision rule of a strategy type, from its definition in spec 4.2.

    The returned function has an attribute `uses_throws`: when False, the turn
    chain can merge states that differ only in the number of throws made.
    """
    rule = _rule(strategy_type, params, target)
    rule.uses_throws = strategy_type in ("max_throws", "combined")  # type: ignore[attr-defined]
    # Distance to the target beyond which the rule ignores the banked score.
    close = params.get("close_to_win_points") if strategy_type == "game_state" else None
    rule.score_horizon = close or 0  # type: ignore[attr-defined]
    return rule


def _rule(strategy_type: str, params: dict, target: int) -> Policy:
    p = params
    if strategy_type == "threshold":
        return lambda t, n, s: 0.0 if t >= p["threshold"] else 1.0
    if strategy_type == "max_throws":
        return lambda t, n, s: 0.0 if n >= p["max_throws"] else 1.0
    if strategy_type == "combined":
        def combined(t: int, n: int, s: int) -> float:
            a, b = t >= p["threshold"], n >= p["max_throws"]
            return 0.0 if ((a or b) if p["logic"] == "or" else (a and b)) else 1.0
        return combined
    if strategy_type == "random":
        return lambda t, n, s: float(p["p_continue"])
    if strategy_type == "game_state":
        # Alone in the game the player is always "leading" (decision 5 / spec 4.1).
        def game_state(t: int, n: int, s: int) -> float:
            close = p.get("close_to_win_points")
            if close is not None and target - s <= close:
                ct = p.get("close_threshold")
                return 1.0 if ct is None else (0.0 if t >= ct else 1.0)
            return 0.0 if t >= p["leading_threshold"] else 1.0
        return game_state
    raise ValueError(f"no exact model for strategy type {strategy_type!r}")


@dataclass
class TurnResult:
    outcomes: dict[int, float]   # turn score -> probability (the turn ends at target automatically)
    expected_throws: float
    p_bust_zero: float
    p_bust_negative: float
    pruned: float
    max_total: int = 0           # the largest turn total still in play with non-negligible probability
    throws_sd: float = 0.0       # standard deviation of the number of throws in a turn

    @property
    def mean(self) -> float:
        return sum(v * p for v, p in self.outcomes.items())

    @property
    def variance(self) -> float:
        m = self.mean
        return sum((v - m) ** 2 * p for v, p in self.outcomes.items())


def turn_result(policy: Policy, throw_dist: dict[int, float], banked: int, target: int,
                max_steps: int = 10_000) -> TurnResult:
    """Exact outcome of one turn started with `banked` points (spec 2.3, decision 1)."""
    outcomes: dict[int, float] = defaultdict(float)
    frontier: dict[tuple[int, int], float] = {(0, 0): 1.0}   # (turn points, throws), about to throw
    track_throws = getattr(policy, "uses_throws", True)
    expected_throws = bust0 = bustn = pruned = 0.0
    max_total = 0
    second_moment = 0.0          # E[N^2] for the number of throws N
    for step in range(1, max_steps + 1):
        if not frontier:
            break
        live = sum(frontier.values())
        nxt: dict[tuple[int, int], float] = defaultdict(float)
        for (t, n), p in frontier.items():
            expected_throws += p
            for v, q in throw_dist.items():
                pq = p * q
                if v <= 0:                         # zero or negative: the turn scores the throw itself
                    outcomes[v] += pq
                    if v == 0:
                        bust0 += pq
                    else:
                        bustn += pq
                    continue
                t2, n2 = t + v, n + 1
                if banked + t2 >= target:          # reaching the target banks automatically
                    outcomes[t2] += pq
                    continue
                c = policy(t2, n2, banked)
                if c < 1:
                    outcomes[t2] += pq * (1 - c)   # STOP: bank the turn total
                if c > 0:
                    nxt[(t2, n2 if track_throws else 0)] += pq * c   # CONTINUE
        ended = live - sum(nxt.values())           # turns that ended with this throw
        second_moment += ended * step * step
        frontier = {}
        for k, p in nxt.items():
            if p < PRUNE:
                pruned += p
            else:
                frontier[k] = p
                max_total = max(max_total, k[0])
    else:  # pragma: no cover - only for policies that almost never stop
        pruned += sum(frontier.values())
    var_n = max(0.0, second_moment - expected_throws ** 2)
    return TurnResult(dict(outcomes), expected_throws, bust0, bustn, pruned, max_total, math.sqrt(var_n))


@dataclass
class GameResult:
    """Exact distribution of the number of turns a single player needs to reach the target."""

    p_turns: np.ndarray          # p_turns[k-1] = P(target reached on turn k), k = 1..max_turns
    p_unfinished: float          # P(target not reached within max_turns)
    lost_mass: float             # probability dropped by pruning or the lower score bound (should be ~0)

    @property
    def p_finished(self) -> float:
        return float(self.p_turns.sum())

    def _cond(self) -> np.ndarray:
        return self.p_turns / self.p_turns.sum()

    @property
    def mean(self) -> float:
        """Mean turns to target among games that reached it (the Analyse definition)."""
        k = np.arange(1, len(self.p_turns) + 1)
        return float((k * self._cond()).sum())

    @property
    def sd(self) -> float:
        k = np.arange(1, len(self.p_turns) + 1)
        c = self._cond()
        m = (k * c).sum()
        return float(math.sqrt(((k - m) ** 2 * c).sum()))

    def quantile(self, q: float) -> float:
        """Quantile of turns to target (lower value at an exact tie, like a median of integers)."""
        cdf = np.cumsum(self._cond())
        return float(np.searchsorted(cdf, q - 1e-12) + 1)

    @property
    def median(self) -> float:
        cdf = np.cumsum(self._cond())
        lo = int(np.searchsorted(cdf, 0.5 - 1e-12)) + 1
        # For an even sample, the median averages the two middle values; with a continuous
        # CDF crossing 0.5 inside a value both middles are that value.
        return float(lo)

    def cdf(self) -> np.ndarray:
        return np.cumsum(self._cond())


def game_result(policy: Policy, throw_dist: dict[int, float], target: int, max_turns: int,
                lower_bound: int | None = None) -> GameResult:
    """Exact turns-to-target distribution of a single-player game (spec 2.5, decision 3)."""
    values = [v for v in throw_dist if v != 0]
    step = reduce(math.gcd, [abs(v) for v in values], 0) or 1
    worst = min(min(throw_dist), 0)
    lo = lower_bound if lower_bound is not None else min(-6000, 20 * worst)
    lo = (lo // step) * step
    hi = target - 1
    scores = list(range(lo, hi + 1, step)) if lo <= hi else []
    index = {s: i for i, s in enumerate(scores)}
    n = len(scores)
    trans = np.zeros((n, n))          # banked score -> banked score, staying below the target
    win = np.zeros(n)                 # P(reaching the target in this turn)
    clamp = np.zeros(n)               # mass pushed below the lower bound (kept at the bound)
    lost = 0.0
    # Far from the target a turn cannot reach it and the rule ignores the score, so
    # the outcome is the same for every such score: solve that turn once.
    free = turn_result(policy, throw_dist, 0, 10**12)
    reach = max(free.max_total + max(throw_dist), getattr(policy, "score_horizon", 0)) + 1
    for s in scores:
        tr = free if target - s > reach else turn_result(policy, throw_dist, s, target)
        lost = max(lost, tr.pruned)
        i = index[s]
        for v, p in tr.outcomes.items():
            s2 = s + v
            if s2 >= target:
                win[i] += p
            elif s2 < lo:
                trans[i, 0] += p
                clamp[i] += p
            else:
                trans[i, index[s2]] += p
    dist = np.zeros(n)
    dist[index[0]] = 1.0
    p_turns = np.zeros(max_turns)
    clamped = 0.0
    for k in range(max_turns):
        p_turns[k] = dist @ win
        clamped += float(dist @ clamp)
        dist = dist @ trans
    return GameResult(p_turns, float(dist.sum()), lost + clamped)


def throw_distribution(weights=None, scoring: Scoring = DEFAULT_SCORING) -> dict[int, float]:
    """Throw score -> probability, leaving out scores that cannot occur with these weights."""
    dist = exact_throw_distribution(tuple(weights) if weights else None, scoring)
    return {v: p for v, p in dist.items() if p > 0}
