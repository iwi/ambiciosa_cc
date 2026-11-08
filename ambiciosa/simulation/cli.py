"""The `ambiciosa` command.

    ambiciosa simulate config.yaml [--games N] [--seed N] [--workers N] [--record-level L]
    ambiciosa runs                         list stored runs
    ambiciosa summary RUN_ID               headline numbers of one run
    ambiciosa export RUN_ID... --out DIR   Parquet (default) or CSV, one file per table
    ambiciosa presets                      the ready-made strategies
    ambiciosa benchmark                    games per second on this machine
    ambiciosa serve                        the web app at http://localhost:8000
    ambiciosa validate                     simulated games against exact results

The database is ./ambiciosa.duckdb unless --db or AMBICIOSA_DB says otherwise.
A RUN_ID may be shortened to any unique prefix.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import __version__

DEFAULT_DB = "ambiciosa.duckdb"


def _db_path(args: argparse.Namespace) -> str:
    return args.db or os.environ.get("AMBICIOSA_DB") or DEFAULT_DB


def _open_db(args: argparse.Namespace, *, read_only: bool = False):
    from ..persistence import Database

    path = _db_path(args)
    if read_only and not Path(path).exists():
        raise SystemExit(f"no database at {path}; run a simulation first or pass --db")
    return Database(path, read_only=read_only)


def _resolve_run(db, prefix: str) -> str:
    ids = [str(r["simulation_id"]) for r in db.query("SELECT simulation_id FROM simulation")]
    matches = [i for i in ids if i.startswith(prefix.lower())]
    if not matches:
        raise SystemExit(f"no run matches {prefix!r}")
    if len(matches) > 1:
        raise SystemExit(f"{prefix!r} matches {len(matches)} runs; give more characters")
    return matches[0]


def _fmt(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:,.3f}" if abs(value) < 10 else f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    cells = [[title for _, title in columns]] + [[_fmt(r.get(key)) for key, _ in columns] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    numeric = [all(isinstance(r.get(key), int | float) or r.get(key) is None for r in rows) for key, _ in columns]
    lines = []
    for n, row in enumerate(cells):
        lines.append("  ".join(
            (c.rjust(w) if numeric[i] else c.ljust(w)) for i, (c, w) in enumerate(zip(row, widths, strict=True))
        ).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


SUMMARY_COLUMNS = [
    ("display_name", "Player"),
    ("strategy_name", "Strategy"),
    ("games", "Games"),
    ("wins", "Wins"),
    ("win_rate", "Win rate"),
    ("mean_turns_to_win", "Turns to win"),
    ("points_per_turn", "Pts/turn"),
    ("throws_per_turn", "Throws/turn"),
    ("bust_rate", "Bust rate"),
]


def _print_summary(db, sim_id: str) -> None:
    from ..persistence import run_overview, strategy_summary

    sim = db.get_simulation(sim_id)
    ov = run_overview(db, sim_id)
    print(f"\n{sim['name']}  ({sim_id})")
    print(
        f"status {sim['status']} · {sim['n_games_completed']:,} of {sim['n_games_requested']:,} games · "
        f"record level {sim['record_level']} · master seed {sim['master_seed']}"
    )
    if ov["games"]:
        print(
            f"finished {ov['finished']:,} · unfinished {ov['unfinished']:,} · shared wins {ov['shared_wins']:,} · "
            f"mean rounds {ov['mean_rounds']:.1f}\n"
        )
        print(_table(strategy_summary(db, sim_id), SUMMARY_COLUMNS))


# ---------------------------------------------------------------- commands


def cmd_simulate(args: argparse.Namespace) -> int:
    from .config import SimulationConfig
    from .runner import SimulationRunner

    config = SimulationConfig.from_yaml(
        args.config,
        n_games=args.games,
        master_seed=args.seed,
        workers=args.workers,
        record_level=args.record_level,
        name=args.name,
    )
    db = _open_db(args)
    tty = sys.stderr.isatty()
    last = [0.0]

    def show(p) -> None:
        now = time.monotonic()
        if not p.done and not tty and now - last[0] < 5:
            return
        last[0] = now
        line = (
            f"{p.games_completed:,}/{p.games_requested:,} games ({p.fraction:.0%}) · "
            f"{p.rate:,.0f} games/s · elapsed {_duration(p.elapsed_s)} · ETA {_duration(p.eta_s)}"
        )
        if tty:
            print("\r" + line.ljust(90), end="" if not p.done else "\n", file=sys.stderr, flush=True)
        else:
            print(line, file=sys.stderr, flush=True)

    print(
        f"Simulating {config.n_games:,} games of {config.name!r} with {config.workers} worker(s), "
        f"record level {config.record_level}, master seed {config.master_seed} → {_db_path(args)}",
        file=sys.stderr,
    )
    runner = SimulationRunner(db)
    final = runner.run(config, on_progress=None if args.quiet else show)
    if final.status == "failed":
        print(f"Simulation failed: {final.error}", file=sys.stderr)
    elif final.status == "cancelled":
        print(f"Cancelled; {final.games_completed:,} completed games were kept.", file=sys.stderr)
    _print_summary(db, str(final.simulation_id))
    db.close()
    return 0 if final.status == "completed" else 1


def cmd_runs(args: argparse.Namespace) -> int:
    db = _open_db(args, read_only=True)
    rows = db.list_simulations(args.source)
    for r in rows:
        r["id"] = str(r["simulation_id"])[:8]
        r["created"] = r["created_at"].strftime("%Y-%m-%d %H:%M")
        r["source"] = str(r["source"])
        r["status"] = str(r["status"])
        r["record_level"] = str(r["record_level"])
    if not rows:
        print("No runs stored yet.")
    else:
        print(_table(rows, [("id", "Run"), ("created", "Created"), ("source", "Source"), ("status", "Status"),
                            ("n_games_completed", "Games"), ("record_level", "Level"), ("name", "Name")]))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    db = _open_db(args, read_only=True)
    _print_summary(db, _resolve_run(db, args.run))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from ..persistence import export_simulations

    db = _open_db(args, read_only=True)
    ids = [_resolve_run(db, r) for r in args.runs]
    for path in export_simulations(db, ids, args.out, args.format):
        print(path)
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    from ..strategies import PRESETS

    rows = [{"name": p.name, "type": p.type, "params": ", ".join(f"{k}={v}" for k, v in p.params.items())} for p in PRESETS]
    print(_table(rows, [("name", "Preset"), ("type", "Type"), ("params", "Parameters")]))
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from ..persistence import Database
    from .config import SimulationConfig
    from .runner import SimulationRunner

    levels = args.levels.split(",")
    worker_counts = sorted({1, args.workers or os.cpu_count() or 1})
    print(f"ambiciosa {__version__} · Python {sys.version.split()[0]} · {os.cpu_count()} CPU(s)")
    print(f"{args.games:,} two-player games, 'Stop at 30' vs 'Stop at 50', in-memory database\n")
    rows = []
    for level in levels:
        for workers in worker_counts:
            db = Database(":memory:")
            cfg = SimulationConfig(n_games=args.games, master_seed=1, workers=workers, record_level=level,
                                   players=["Stop at 30", "Stop at 50"])
            t0 = time.perf_counter()
            p = SimulationRunner(db).run(cfg)
            elapsed = time.perf_counter() - t0
            throws = db.query("SELECT sum(total_throws) n FROM game_player")[0]["n"]
            rows.append({"level": level, "workers": workers, "seconds": elapsed,
                         "games_s": p.games_completed / elapsed, "throws_s": throws / elapsed})
            db.close()
    print(_table(rows, [("level", "Level"), ("workers", "Workers"), ("seconds", "Seconds"),
                        ("games_s", "Games/s"), ("throws_s", "Throws/s")]))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    import platform

    from ..validation.suite import CASES, report_markdown, run_suite

    cases = CASES[:3] if args.quick else CASES
    workers = args.workers or os.cpu_count() or 1
    print(f"Validating {len(cases)} configurations against exact results, {args.games:,} games each "
          f"({workers} worker(s))...", file=sys.stderr)
    t0 = time.perf_counter()

    def show(r) -> None:
        bad = [c for c in r.checks if not c.passed]
        print(f"  {'pass' if not bad else 'FAIL'}  {r.case.name}" + (f"  ({', '.join(c.figure for c in bad)})" if bad else ""),
              file=sys.stderr)

    results = run_suite(args.games, workers, args.seed, cases, on_case=show)
    elapsed = time.perf_counter() - t0
    total = sum(len(r.checks) for r in results)
    failed = sum(not c.passed for r in results for c in r.checks)
    meta = {"Software version": __version__, "Python": platform.python_version(), "Master seed": args.seed,
            "Games per configuration": f"{args.games:,}", "Time": f"{elapsed:.0f} s"}
    if args.report:
        Path(args.report).write_text(report_markdown(results, meta), encoding="utf-8")
        print(f"Report written to {args.report}", file=sys.stderr)
    print(f"{total - failed} of {total} checks passed in {elapsed:.0f} s.")
    return 0 if failed == 0 else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from ..api import create_app
    from ..api.main import default_static_dir

    app = create_app(_db_path(args))
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    if default_static_dir() is None:
        print("note: the web app is not built (web/ → npm run build); only the API is served", file=sys.stderr)
    if app.state.interrupted_runs:
        print(f"{app.state.interrupted_runs} run(s) left running by an earlier session were marked failed",
              file=sys.stderr)
    print(f"Ambiciosa {__version__} · database {_db_path(args)} · {url}  (Ctrl+C to stop)", file=sys.stderr)
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# ------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ambiciosa", description="Simulate and analyse the dice game Ambiciosa.")
    parser.add_argument("--version", action="version", version=f"ambiciosa {__version__}")
    parser.add_argument("--db", help=f"DuckDB file (default: $AMBICIOSA_DB or ./{DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("simulate", help="run a simulation from a YAML config")
    p.add_argument("config", type=Path)
    p.add_argument("--games", type=int, help="override n_games")
    p.add_argument("--seed", type=int, help="override master_seed")
    p.add_argument("--workers", type=int, help="override workers (default: all CPUs)")
    p.add_argument("--record-level", choices=("summary", "turns", "full"))
    p.add_argument("--name", help="override the run name")
    p.add_argument("--quiet", action="store_true", help="no progress line")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("runs", help="list stored runs")
    p.add_argument("--source", choices=("simulation", "interactive"))
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("summary", help="show the results of one run")
    p.add_argument("run", help="run id or unique prefix")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("export", help="export runs to Parquet or CSV")
    p.add_argument("runs", nargs="+", help="run ids or unique prefixes")
    p.add_argument("--out", required=True, type=Path, help="output directory")
    p.add_argument("--format", choices=("parquet", "csv"), default="parquet")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("presets", help="list the ready-made strategies")
    p.set_defaults(func=cmd_presets)

    p = sub.add_parser("benchmark", help="measure games per second")
    p.add_argument("--games", type=int, default=20_000)
    p.add_argument("--workers", type=int, help="parallel run size (default: all CPUs)")
    p.add_argument("--levels", default="summary,turns,full")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("validate", help="check simulated games against exact results")
    p.add_argument("--games", type=int, default=20_000, help="games per configuration (default 20,000)")
    p.add_argument("--workers", type=int, help="parallel processes (default: all CPUs)")
    p.add_argument("--seed", type=int, default=20261108)
    p.add_argument("--quick", action="store_true", help="three configurations only")
    p.add_argument("--report", type=Path, help="write a Markdown report to this file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("serve", help="start the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        # pydantic's ValidationError is a ValueError: show it without a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
