"""Simulated games against exact results: the Phase 7 correctness check.

Each case is a single-player configuration with an exact model
(validation/exact.py). The case is simulated with the real runner and
database, and every compared figure must agree within sampling error:

* turns to reach the target: mean and median (z-scores), standard deviation,
  and the whole distribution (Kolmogorov-Smirnov distance);
* games stopped at the turn limit (z-score against the exact probability);
* single turns played far from the target: mean turn score, share of turns
  scoring nothing, and throws per turn (z-scores).

|z| below 4 and a KS distance below its 0.1% critical value pass; with about
20 figures per run, a correct simulator fails a check by chance well under
once in a thousand runs.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..engine.scoring import Scoring
from ..persistence import Database
from ..simulation import SimulationConfig, SimulationRunner
from .exact import game_result, policy_for, throw_distribution, turn_result

Z_LIMIT = 4.0
KS_COEFF = 1.95   # critical value 1.95/sqrt(n) at the 0.1% level


@dataclass(frozen=True)
class Case:
    name: str
    strategy_type: str
    params: dict
    target: int = 1000
    max_turns: int = 500
    face_weights: tuple[float, ...] | None = None
    scoring: dict | None = None


CASES: tuple[Case, ...] = (
    Case("Stop at 30", "threshold", {"threshold": 30}),
    Case("Stop at 50", "threshold", {"threshold": 50}),
    Case("Three throws", "max_throws", {"max_throws": 3}),
    Case("50 points or 4 throws", "combined", {"threshold": 50, "max_throws": 4, "logic": "or"}),
    Case("40 points and 2 throws", "combined", {"threshold": 40, "max_throws": 2, "logic": "and"}),
    Case("Coin flip 75%", "random", {"p_continue": 0.75}),
    Case("Safe ahead, going for the win", "game_state",
         {"leading_threshold": 30, "trailing_threshold": 60, "close_to_win_points": 100, "close_threshold": None}),
    Case("Loaded dice, changed scores", "threshold", {"threshold": 40},
         face_weights=(1, 1, 1, 1, 1.5, 2), scoring={"ace": 15, "king": 5, "three_tens": -150, "three_nines": -200}),
    Case("Short game, tight turn limit", "threshold", {"threshold": 60}, target=300, max_turns=25),
)


@dataclass
class Check:
    figure: str
    exact: float
    simulated: float
    z: float | None = None              # for z-tested figures
    statistic: float | None = None      # for distribution tests
    limit: float | None = None

    @property
    def passed(self) -> bool:
        if self.z is not None:
            return abs(self.z) < Z_LIMIT
        if self.statistic is not None and self.limit is not None:
            return self.statistic < self.limit
        return True


@dataclass
class CaseResult:
    case: Case
    games: int
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _z(sim: float, exact: float, se: float) -> float:
    return 0.0 if se == 0 else (sim - exact) / se


def run_case(db: Database, case: Case, n_games: int, master_seed: int, workers: int) -> CaseResult:
    config = SimulationConfig(
        name=f"Validation: {case.name}", n_games=n_games, master_seed=master_seed, workers=workers,
        record_level="turns", target=case.target, max_turns=case.max_turns, face_weights=case.face_weights,
        scoring=case.scoring or {},
        players=[{"name": case.name, "strategy": {"name": f"Validation: {case.name}", "type": case.strategy_type,
                                                    "params": case.params}}],
    )
    progress = SimulationRunner(db).run(config)
    if progress.status != "completed":
        raise RuntimeError(f"validation run failed: {progress.error}")
    sid = str(progress.simulation_id)

    scoring = Scoring.from_dict(case.scoring)
    dist = throw_distribution(config.face_weights, scoring)
    policy = policy_for(case.strategy_type, case.params, case.target)
    exact = game_result(policy, dist, case.target, case.max_turns)
    free = turn_result(policy, dist, 0, 10**12)
    reach = max(free.max_total + max(dist), getattr(policy, "score_horizon", 0)) + 1

    turns_taken = np.array([r[0] for r in db.conn.execute(
        "SELECT gp.turns_taken FROM game_player gp JOIN game g USING (game_id) "
        "WHERE g.simulation_id = ? AND gp.final_score >= ?", [sid, case.target]).fetchall()])
    unfinished = db.conn.execute("SELECT count(*) FROM game WHERE simulation_id = ? AND status = 'unfinished'",
                                 [sid]).fetchone()[0]
    result = CaseResult(case, n_games)
    n = len(turns_taken)
    if n:
        result.checks.append(Check("Mean turns to target", exact.mean, float(turns_taken.mean()),
                                   z=_z(float(turns_taken.mean()), exact.mean, exact.sd / math.sqrt(n))))
        # Sample median: standard error from the exact density at the median.
        cdf = exact.cdf()
        m = int(exact.median)
        density = exact.p_turns[m - 1] / exact.p_finished if m >= 1 else 0
        med_se = 1 / (2 * density * math.sqrt(n)) if density > 0 else 0
        sim_median = float(np.median(turns_taken))
        result.checks.append(Check("Median turns to target", exact.median, sim_median,
                                   z=_z(sim_median, exact.median, max(med_se, 0.5 / math.sqrt(n)))))
        sim_sd = float(turns_taken.std(ddof=1)) if n > 1 else 0.0
        # SD of a sample: standard error about sd * sqrt((kurtosis - 1) / (4n)); use the exact moments.
        k = np.arange(1, len(exact.p_turns) + 1)
        c = exact.p_turns / exact.p_finished
        mu4 = float((((k - exact.mean) ** 4) * c).sum())
        var = exact.sd ** 2
        sd_se = math.sqrt(max(mu4 - var ** 2, 0) / (4 * var * n)) if var > 0 else 0
        result.checks.append(Check("SD of turns to target", exact.sd, sim_sd, z=_z(sim_sd, exact.sd, sd_se)))
        counts = np.bincount(turns_taken, minlength=len(cdf) + 1)[1:len(cdf) + 1]
        ks = float(np.max(np.abs(np.cumsum(counts) / n - cdf)))
        result.checks.append(Check("Distribution of turns to target (KS distance)", 0.0, ks,
                                   statistic=ks, limit=KS_COEFF / math.sqrt(n)))
    p_unf = exact.p_unfinished
    expected_unf = p_unf * n_games
    result.checks.append(Check("Games stopped at the turn limit", expected_unf, float(unfinished),
                               z=_z(unfinished, expected_unf, math.sqrt(max(n_games * p_unf * (1 - p_unf), 1e-12)))
                               if expected_unf >= 1 or unfinished > 3 else None))

    far = db.conn.execute(
        "SELECT count(*), avg(t.turn_score), avg((t.end_reason = 'bust_zero')::INT), avg(t.n_throws) "
        "FROM turn t JOIN game g USING (game_id) WHERE g.simulation_id = ? AND ? - (t.banked_after - t.turn_score) > ?",
        [sid, case.target, reach]).fetchone()
    m_turns, mean_score, bust0, mean_throws = far
    if m_turns:
        se = math.sqrt
        result.checks.append(Check("Mean turn score (far from target)", free.mean, mean_score,
                                   z=_z(mean_score, free.mean, se(free.variance / m_turns))))
        result.checks.append(Check("Turns scoring nothing (far from target)", free.p_bust_zero, bust0,
                                   z=_z(bust0, free.p_bust_zero, se(free.p_bust_zero * (1 - free.p_bust_zero) / m_turns))))
        result.checks.append(Check("Throws per turn (far from target)", free.expected_throws, mean_throws,
                                   z=_z(mean_throws, free.expected_throws, free.throws_sd / se(m_turns))))
    return result


def run_suite(n_games: int = 20_000, workers: int = 1, master_seed: int = 20261108,
              cases: tuple[Case, ...] = CASES, db: Database | None = None,
              on_case: Callable[[CaseResult], None] | None = None) -> list[CaseResult]:
    own = db is None
    db = db or Database(":memory:")
    results = []
    try:
        for i, case in enumerate(cases):
            r = run_case(db, case, n_games, master_seed + i, workers)
            results.append(r)
            if on_case:
                on_case(r)
    finally:
        if own:
            db.close()
    return results


def report_markdown(results: list[CaseResult], meta: dict[str, Any]) -> str:
    lines = ["# Validation report", ""]
    lines += [f"- {k}: {v}" for k, v in meta.items()]
    total = sum(len(r.checks) for r in results)
    failed = sum(not c.passed for r in results for c in r.checks)
    lines += ["", f"**{total - failed} of {total} checks passed.** A check passes when |z| < {Z_LIMIT:g}, or for the "
              f"distribution, when the KS distance is below 1.95/√n (0.1% level).", ""]
    for r in results:
        c = r.case
        extra = []
        if c.face_weights:
            extra.append(f"face weights {list(c.face_weights)}")
        if c.scoring:
            extra.append(f"scores {c.scoring}")
        lines += [f"## {c.name}", "",
                  f"`{c.strategy_type}` {c.params}; target {c.target}, turn limit {c.max_turns}"
                  + (f"; {', '.join(extra)}" if extra else "") + f"; {r.games:,} games.", "",
                  "| Figure | Exact | Simulated | Test | Result |", "| --- | ---: | ---: | ---: | --- |"]
        for ch in r.checks:
            test = (f"z = {ch.z:+.2f}" if ch.z is not None else
                    f"{ch.statistic:.4f} < {ch.limit:.4f}" if ch.statistic is not None else "–")
            lines.append(f"| {ch.figure} | {ch.exact:,.4f} | {ch.simulated:,.4f} | {test} | "
                         f"{'pass' if ch.passed else '**FAIL**'} |")
        lines.append("")
    return "\n".join(lines)
