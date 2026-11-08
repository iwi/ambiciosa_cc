# Ambiciosa Simulator

Play, simulate and analyse the dice game Ambiciosa. Play against computer players in your browser, run thousands or millions of games between playing strategies, and compare the results. Everything runs locally: a small Python web server, a DuckDB database file and a browser.

**Version 1.0.0**: all seven development phases are complete.

## Quick start

You need Python 3.12 or later. From the project folder (the one containing `pyproject.toml`):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ambiciosa serve                    # opens http://localhost:8000
```

Or, with [uv](https://docs.astral.sh/uv/) and the exact tested versions: `uv sync`, then `uv run ambiciosa serve`.

**The full installation and user guide is in [docs/USER_GUIDE.md](docs/USER_GUIDE.md)**: step-by-step installation for Windows, macOS and Linux, every page of the app, the command line, simulation files, reading the results from R, and troubleshooting.

## What it does

- **Play**: up to six players, human or computer, with the computer players' decisions explained.
- **Simulate**: many games between strategies, in parallel, with live progress, cancelling and reproducible seeds.
- **Strategies**: five configurable strategy types, versioned so that results always refer to the exact settings used.
- **Analyse**: win rates with confidence intervals; turns to reach the target (mean, median, minimum, maximum, standard deviation); points and throws per turn; distributions, turn and throw details, every game's record; and comparisons of strategies and runs.
- Configurable rules: target, end rule, turn limit, loaded dice, and the value of every scoring combination.

## Correctness

- `ambiciosa validate` compares simulated games with exact results from an independent mathematical model of the rules. Release result: 72 of 72 checks passed ([docs/VALIDATION.md](docs/VALIDATION.md)).
- Over 600 automated tests (`pytest`), covering all 216 throws, all game rules, strategies, reproducibility, storage, every analysis metric, and the app in a real browser.

## Command line

```bash
ambiciosa simulate examples/cautious_vs_bold.yaml   # a simulation without the browser
ambiciosa runs | summary <id> | export <id> --out dir/
ambiciosa validate | benchmark | presets | serve
```

## Project layout

```text
ambiciosa/   engine, strategies, simulation, persistence, analysis, validation, api, web_dist
web/         React + TypeScript source of the web app
tests/       unit, integration and browser tests
docs/        user guide and validation report
examples/    sample simulation files
```

The architecture, rule decisions and the record of each phase are in the project's architecture document.
