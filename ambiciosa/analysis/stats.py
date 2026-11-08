"""Analysis of one run: player metrics, distributions, turns and throws.

Everything is computed in DuckDB from the stored rows, so a million-game run
is summarised without loading it into Python. What can be shown depends on
the run's recording level:

    summary  players, play position, turns to target, final scores, game length
    turns    + how turns end, turn scores, throws per turn
    full     + face frequencies and throw scores, against their exact expectations

Definitions used throughout (and shown in the app):

* Win share: 1 for a sole win, 1/n each for an n-way shared win, else 0.
  Win rate = mean win share; its 95% interval is the Wilson score interval.
* Turns to target: turns taken by players whose final score reached the
  target (in first_to_target games, only the winner; in equal_turns games,
  everyone who passed it).
* Per-turn rates are ratios of totals (total points / total turns), so long
  games weigh in proportion to their turns.
"""

from __future__ import annotations

import json
import math
import uuid
from itertools import product
from typing import Any

from ..engine import normalise_weights
from ..engine.scoring import DEFAULT_SCORING, Scoring
from ..persistence import Database, run_overview

Z95 = 1.959963984540054
MAX_BINS = 60
FACES = ("9", "10", "J", "Q", "K", "A")  # face codes 0-5 (decision 12)


# ---------------------------------------------------------------- helpers


def wilson(successes: float, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (successes may be fractional for shared wins)."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if successes <= 0 else max(0.0, centre - half)
    high = 1.0 if successes >= n else min(1.0, centre + half)  # exact ends despite rounding
    return low, high


def chi2_sf_df5(x: float) -> float:
    """P(X >= x) for a chi-squared variable with 5 degrees of freedom (closed form for odd df)."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2)) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2) * (1 + x / 3)


def nice_width(span: float, max_bins: int = MAX_BINS, base: int = 1) -> int:
    """A round bin width (1, 2, 5 × 10^k, at least `base`) giving at most max_bins bins."""
    if span <= 0:
        return base
    raw = span / max_bins
    for mag in (10 ** k for k in range(0, 12)):
        for step in (1, 2, 5):
            w = step * mag
            if w >= raw and w >= base:
                return w
    return int(raw) + 1


def exact_throw_distribution(weights: tuple[float, ...] | None,
                             scoring: Scoring = DEFAULT_SCORING) -> dict[int, float]:
    """Probability of each throw score with the given face weights and scoring (exact, over all 216 throws)."""
    w = normalise_weights(weights)
    dist: dict[int, float] = {}
    for a, b, c in product(range(6), repeat=3):
        s = scoring.table[36 * a + 6 * b + c]
        dist[s] = dist.get(s, 0.0) + w[a] * w[b] * w[c]
    return dict(sorted(dist.items()))


def _rows(db: Database, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    return db.query(sql, params)


def _histogram(db: Database, value_sql: str, from_sql: str, params: list[Any], *, by_seat: bool,
               base: int = 1) -> dict[str, Any]:
    """Shared-bin histogram of an integer value, overall or per seat.

    Returns bin starts, the bin width, counts and shares (share of that
    series' total, so series of different sizes compare directly).
    """
    lim = _rows(db, f"SELECT min({value_sql}) lo, max({value_sql}) hi FROM {from_sql}", params)[0]
    if lim["lo"] is None:
        return {"bin_start": [], "bin_width": base, "series": []}
    lo, hi = int(lim["lo"]), int(lim["hi"])
    width = nice_width(hi - lo + 1, base=base)
    start = (lo // width) * width
    n_bins = (hi - start) // width + 1
    group = "seat, " if by_seat else ""
    rows = _rows(
        db,
        f"SELECT {group}(({value_sql}) - {start}) // {width} AS b, count(*) AS n FROM {from_sql} "
        f"GROUP BY ALL ORDER BY ALL",
        params,
    )
    series: dict[Any, list[int]] = {}
    for r in rows:
        key = r["seat"] if by_seat else "all"
        series.setdefault(key, [0] * n_bins)[int(r["b"])] = int(r["n"])
    out = []
    for key in sorted(series, key=lambda k: (isinstance(k, str), k)):
        counts = series[key]
        total = sum(counts)
        out.append({"seat": None if key == "all" else key, "counts": counts, "total": total,
                    "shares": [c / total for c in counts] if total else counts})
    return {"bin_start": [start + i * width for i in range(n_bins)], "bin_width": width, "series": out}


# ---------------------------------------------------------------- sections


def player_metrics(db: Database, sid: str, target: int) -> list[dict[str, Any]]:
    rows = _rows(
        db,
        """
        WITH gp AS (
            SELECT gp.*, g.status,
                   CASE WHEN gp.is_winner THEN 1.0 / count(*) FILTER (WHERE gp.is_winner)
                        OVER (PARTITION BY gp.game_id) ELSE 0.0 END AS win_share
            FROM game_player gp JOIN game g USING (game_id) WHERE g.simulation_id = ?
        )
        SELECT seat,
               any_value(display_name) AS display_name,
               any_value(player_type) AS player_type,
               any_value(strategy_version_id) AS strategy_version_id,
               count(*) AS games,
               sum(win_share) AS wins,
               avg(win_share) AS win_rate,
               count(*) FILTER (WHERE final_score >= ?) AS reached_target,
               avg(turns_taken) FILTER (WHERE final_score >= ?) AS turns_to_target_mean,
               median(turns_taken) FILTER (WHERE final_score >= ?) AS turns_to_target_median,
               quantile_cont(turns_taken, 0.1) FILTER (WHERE final_score >= ?) AS turns_to_target_p10,
               quantile_cont(turns_taken, 0.9) FILTER (WHERE final_score >= ?) AS turns_to_target_p90,
               min(turns_taken) FILTER (WHERE final_score >= ?) AS turns_to_target_min,
               max(turns_taken) FILTER (WHERE final_score >= ?) AS turns_to_target_max,
               stddev_samp(turns_taken) FILTER (WHERE final_score >= ?) AS turns_to_target_sd,
               avg(final_score) AS mean_final_score,
               stddev_samp(final_score) AS sd_final_score,
               sum(turns_taken) AS turns,
               sum(total_throws) AS throws,
               sum(busts) AS busts,
               sum(final_score) / nullif(sum(turns_taken), 0) AS points_per_turn,
               sum(total_throws) / nullif(sum(turns_taken), 0) AS throws_per_turn,
               sum(busts) / nullif(sum(turns_taken), 0) AS bust_rate
        FROM gp GROUP BY seat ORDER BY seat
        """,
        [sid, *[target] * 8],
    )
    labels = {str(r["strategy_version_id"]): r for r in _rows(
        db, "SELECT strategy_version_id, name, version, type FROM strategy WHERE strategy_version_id IN "
            "(SELECT DISTINCT strategy_version_id FROM game_player JOIN game USING (game_id) WHERE simulation_id = ?)",
        [sid])}
    for r in rows:
        ci = wilson(r["wins"], r["games"])
        r["win_rate_low"], r["win_rate_high"] = ci if ci else (None, None)
        r["reached_target_rate"] = r["reached_target"] / r["games"] if r["games"] else None
        st = labels.get(str(r["strategy_version_id"])) if r["strategy_version_id"] else None
        r["strategy_name"] = st["name"] if st else None
        r["strategy_version"] = st["version"] if st else None
        r["strategy_type"] = str(st["type"]) if st else None
    return rows


def play_position(db: Database, sid: str) -> dict[str, Any]:
    """Win rate by position in the playing order, per seat and for everyone together."""
    rows = _rows(
        db,
        """
        WITH gp AS (
            SELECT gp.seat, gp.play_order,
                   CASE WHEN gp.is_winner THEN 1.0 / count(*) FILTER (WHERE gp.is_winner)
                        OVER (PARTITION BY gp.game_id) ELSE 0.0 END AS win_share
            FROM game_player gp JOIN game g USING (game_id) WHERE g.simulation_id = ?
        )
        SELECT seat, play_order, count(*) AS games, sum(win_share) AS wins
        FROM gp GROUP BY GROUPING SETS ((seat, play_order), (play_order)) ORDER BY seat NULLS LAST, play_order
        """,
        [sid],
    )
    out = []
    for r in rows:
        ci = wilson(r["wins"], r["games"])
        out.append({
            "seat": r["seat"], "position": r["play_order"] + 1, "games": r["games"], "wins": r["wins"],
            "win_rate": r["wins"] / r["games"], "win_rate_low": ci[0], "win_rate_high": ci[1],
        })
    return {"rows": out}


def turn_metrics(db: Database, sid: str) -> dict[str, Any]:
    from_turns = "turn t JOIN game g USING (game_id) WHERE g.simulation_id = ?"
    ends = _rows(
        db,
        f"""
        SELECT seat, count(*) AS turns,
               avg((end_reason = 'stop')::INT) AS stop,
               avg((end_reason = 'reached_target')::INT) AS reached_target,
               avg((end_reason = 'bust_zero')::INT) AS bust_zero,
               avg((end_reason = 'bust_negative')::INT) AS bust_negative,
               avg(turn_score) AS mean_turn_score,
               avg(turn_score) FILTER (WHERE end_reason IN ('stop', 'reached_target')) AS mean_banked_score,
               avg(n_throws) AS mean_throws
        FROM {from_turns} GROUP BY seat ORDER BY seat
        """,
        [sid],
    )
    return {
        "end_reasons": ends,
        "turn_score": _histogram(db, "t.turn_score", from_turns, [sid], by_seat=True, base=5),
        "throws_per_turn": _histogram(db, "t.n_throws", from_turns, [sid], by_seat=True),
    }


def throw_metrics(db: Database, sid: str, weights: tuple[float, ...] | None,
                  scoring: Scoring = DEFAULT_SCORING) -> dict[str, Any]:
    from_throws = "throw x JOIN game g USING (game_id) WHERE g.simulation_id = ?"
    faces = {int(r["face"]): int(r["n"]) for r in _rows(
        db,
        f"SELECT face, count(*) n FROM (SELECT unnest([x.die1, x.die2, x.die3]) AS face FROM {from_throws}) "
        "GROUP BY face",
        [sid],
    )}
    total_dice = sum(faces.values())
    w = normalise_weights(weights)
    chi2 = sum((faces.get(i, 0) - total_dice * w[i]) ** 2 / (total_dice * w[i]) for i in range(6) if w[i] > 0)
    impossible = sum(faces.get(i, 0) for i in range(6) if w[i] == 0)

    scores = {int(r["s"]): int(r["n"]) for r in _rows(
        db, f"SELECT x.throw_score s, count(*) n FROM {from_throws} GROUP BY 1", [sid])}
    n_throws = sum(scores.values())
    exact = exact_throw_distribution(weights, scoring)
    exact_mean = sum(s * p for s, p in exact.items())
    observed_mean = sum(s * n for s, n in scores.items()) / n_throws if n_throws else None
    exact_var = sum((s - exact_mean) ** 2 * p for s, p in exact.items())

    def _ender(dist: dict[int, float]) -> float:
        return sum(p for s, p in dist.items() if s <= 0)

    return {
        "n_throws": n_throws,
        "faces": [
            {"face": FACES[i], "code": i, "count": faces.get(i, 0),
             "share": faces.get(i, 0) / total_dice if total_dice else None, "expected_share": w[i]}
            for i in range(6)
        ],
        "face_test": {
            "chi2": chi2, "df": 5, "p_value": chi2_sf_df5(chi2) if all(x > 0 for x in w) else None,
            "impossible_faces": impossible,
        },
        "scores": [
            {"score": s, "count": scores.get(s, 0), "share": scores.get(s, 0) / n_throws if n_throws else None,
             "expected_share": exact.get(s, 0.0)}
            for s in sorted(set(exact) | set(scores))
        ],
        "mean_score": {
            "observed": observed_mean, "expected": exact_mean,
            "standard_error": math.sqrt(exact_var / n_throws) if n_throws else None,
        },
        "turn_ending_rate": {
            "observed": sum(n for s, n in scores.items() if s <= 0) / n_throws if n_throws else None,
            "expected": _ender(exact),
        },
    }


# ------------------------------------------------------------------ main


def run_analysis(db: Database, simulation_id: uuid.UUID | str) -> dict[str, Any]:
    sid = str(simulation_id)
    sim = db.get_simulation(sid)
    config = sim["config"]
    target = int(config.get("target", 1000))
    level = str(sim["record_level"])
    has_turns = level in ("turns", "full")
    has_throws = level == "full"
    from_players = "game_player gp JOIN game g USING (game_id) WHERE g.simulation_id = ?"
    weights = config.get("face_weights")
    scoring = Scoring.from_dict(config.get("scoring"))   # runs stored before decision 11 used the defaults
    specs = {str(r["strategy_version_id"]): r for r in db.query(
        "SELECT strategy_version_id, strategy_id, name, version, type, params, description FROM strategy "
        "WHERE strategy_version_id IN (SELECT unnest(?::UUID[]))",
        [[p["strategy_version_id"] for p in config.get("players", []) if p.get("strategy_version_id")]],
    )}
    seats = []
    for seat, p in enumerate(config.get("players", [])):
        st = specs.get(str(p.get("strategy_version_id")))
        seats.append({
            "seat": seat,
            "name": p["name"],
            "player_type": p.get("player_type", "automated"),
            "strategy": None if st is None else {
                "strategy_version_id": str(st["strategy_version_id"]), "strategy_id": str(st["strategy_id"]),
                "name": st["name"], "version": st["version"], "type": str(st["type"]),
                "params": json.loads(st["params"]), "description": st["description"],
            },
        })
    result: dict[str, Any] = {
        "simulation": {
            "simulation_id": sid,
            "name": sim["name"],
            "source": str(sim["source"]),
            "status": str(sim["status"]),
            "record_level": level,
            "master_seed": sim["master_seed"],
            "n_games_completed": sim["n_games_completed"],
            "target": target,
            "end_rule": config.get("end_rule", "first_to_target"),
            "max_turns": config.get("max_turns"),
            "face_weights": weights,
            "scoring": scoring.as_dict(),
            "scoring_is_default": scoring.is_default,
            "n_games_requested": sim["n_games_requested"],
            "created_at": sim["created_at"],
            "finished_at": sim["finished_at"],
            "software_version": sim["software_version"],
            "single_player": len(seats) == 1,
            "players": seats,
        },
        "available": {"turns": has_turns, "throws": has_throws},
        "overview": run_overview(db, sid),
        "players": player_metrics(db, sid, target),
        "play_position": play_position(db, sid),
        "distributions": {
            "turns_to_target": _histogram(db, "gp.turns_taken", f"{from_players} AND gp.final_score >= ?",
                                          [sid, target], by_seat=True),
            "final_score": _histogram(db, "gp.final_score", from_players, [sid], by_seat=True, base=5),
            "game_length": _histogram(db, "g.n_rounds", "game g WHERE g.simulation_id = ?", [sid], by_seat=False),
        },
        "turns": turn_metrics(db, sid) if has_turns else None,
        "throws": throw_metrics(db, sid, tuple(weights) if weights else None, scoring) if has_throws else None,
    }
    return result
