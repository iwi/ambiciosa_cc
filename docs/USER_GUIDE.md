# Ambiciosa Simulator: installation and user guide

Ambiciosa Simulator lets you play the dice game Ambiciosa against computer players, run thousands or millions of games between playing strategies, and analyse and compare the results. Everything runs on your own computer: a small web server, a DuckDB database file, and the app in your browser.

Contents:

1. [Installing](#1-installing)
2. [Starting the app](#2-starting-the-app)
3. [The game](#3-the-game)
4. [Play](#4-play)
5. [Simulate](#5-simulate)
6. [Strategies](#6-strategies)
7. [Analyse](#7-analyse)
8. [The command line](#8-the-command-line)
9. [Your data: the database, R and exports](#9-your-data-the-database-r-and-exports)
10. [Correctness and speed](#10-correctness-and-speed)
11. [Troubleshooting](#11-troubleshooting)
12. [For developers](#12-for-developers)

---

## 1. Installing

You need **Python 3.12 or later**. Node.js is *not* needed: the built web app is included.

Check your Python version in a terminal (PowerShell on Windows, Terminal on macOS or Linux):

| System | Command |
| --- | --- |
| Windows | `py --version` |
| macOS, Linux | `python3 --version` |

If it is missing or older than 3.12, install it from [python.org](https://www.python.org/downloads/). On Windows, tick **Add python.exe to PATH** in the installer.

### Where to put the project

Unzip the download to a folder of your choice that is **not** synced by OneDrive, iCloud or Dropbox (syncing tools interfere with the database file and the thousands of small files in the Python environment), for example:

- Windows: `C:\Users\<you>\Projects\`
- macOS: `/Users/<you>/Projects/`

The zip contains one folder, `ambiciosa-simulator`. This **project folder** holds `pyproject.toml`; every command below is run from it. On Windows, *Extract All* in Explorer adds a folder of its own, so you may get `ambiciosa-simulator-1.0.0\ambiciosa-simulator\`: the inner folder is the project folder.

### Option A: pip (comes with Python)

Windows (PowerShell):

```powershell
cd C:\Users\<you>\Projects\ambiciosa-simulator
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

macOS or Linux:

```bash
cd ~/Projects/ambiciosa-simulator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Notes:

- If PowerShell says *running scripts is disabled on this system*, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and activate again. In the older Command Prompt, activate with `.venv\Scripts\activate.bat`.
- Keep the quotes in `".[dev]"`; macOS's shell needs them.
- `[dev]` adds the test tools. `pip install -e .` installs only the app.

### Option B: uv (exact, locked versions)

[uv](https://docs.astral.sh/uv/) installs exactly the versions in `uv.lock`, the ones every test in this release was run with:

```bash
cd ambiciosa-simulator
uv sync
```

`uv sync` creates `.venv` itself. Then either activate it as above, or put `uv run` in front of each command (`uv run ambiciosa serve`).

### Check the installation

```bash
ambiciosa --version        # ambiciosa 1.0.0
ambiciosa validate --quick --games 2000   # about a minute: simulated games against exact results
```

### Each new terminal

`cd` into the project folder and activate the environment again (`.venv\Scripts\Activate.ps1` or `source .venv/bin/activate`). Nothing needs reinstalling.

### Updating to a new version

Unzip the new version to a fresh folder and install it as above. Copy your `ambiciosa.duckdb` into the new project folder (or keep using it where it is with `--db`): the new version upgrades the file automatically the first time it opens it. Upgraded files cannot be opened by older versions.

---

## 2. Starting the app

```bash
ambiciosa serve
```

Your browser opens at **http://localhost:8000**. Leave the terminal open while you use the app; press **Ctrl+C** there to stop it.

Options:

| Option | Effect |
| --- | --- |
| `--port 8080` | use another port (if 8000 is taken) |
| `--host 0.0.0.0` | let other computers on your network open it (at your computer's address) |
| `--no-browser` | don't open a browser window |
| `--db path/to/file.duckdb` | use another database file (also: the `AMBICIOSA_DB` environment variable) |

Results are stored in `ambiciosa.duckdb` in the folder you start from, unless you choose another file. Starting from the project folder keeps everything in one place.

The API behind the app is documented at http://localhost:8000/api/docs.

---

## 3. The game

Three poker dice with faces **9, 10, J, Q, K and A**.

**Scoring a throw** (standard values; every value can be changed, see below):

| Throw | Score |
| --- | --- |
| Three Aces | +100 |
| Three Kings | +50 |
| Three 10s | −100 |
| Three 9s | −300 |
| Any other throw | +10 for each Ace, +5 for each King; 0 if there are none |

Three of a kind uses its own value instead of the per-die values, so three Aces score 100, not 30. Three Jacks or three Queens score 0.

**A turn:** throw all three dice.

- A throw scoring **0** ends the turn; the turn scores 0.
- A **negative** throw ends the turn; the turn scores that negative value, whatever was built up before.
- A **positive** throw is added to the turn total. The player then chooses to **stop** (bank the turn total) or **continue** (throw again).

Example: +20, +15, +10, stop: the turn scores 45. But +20, +15, −100: the turn scores −100.

**Winning:** the first player to reach 1,000 points wins, the moment they reach it, even in the middle of a turn. Scores can go negative. With one player, the aim is to reach 1,000 in as few turns as possible.

**Rules you can set** for each game or simulation:

| Rule | Default | Meaning |
| --- | --- | --- |
| Target | 1,000 | points needed to win |
| Game ends | First to the target | or **Equal turns**: once someone reaches the target, the round is finished so everyone has had the same number of turns; the highest total wins, and an exact tie is a shared win |
| Turn limit | 500 | turns per player; a game that reaches it ends unfinished, with no winner |
| Loaded dice | off | a relative weight for each face, the same for all three dice |
| Change the scores | off | the value of each Ace, each King, three Aces, three Kings, three 10s and three 9s: whole numbers from −10,000 to 10,000 |

Whatever scores you choose, a throw scoring 0 or less always ends the turn.

---

## 4. Play

1. **Players** (up to six): give each a name and choose **Human** or **Bot**; a bot plays a strategy from your library. The playing order is drawn at random for each game.
2. **Rules**: as in the table above. The **Scoring** guide beside the form shows the values in force.
3. **Seed** (optional, under *Seed*): the same seed and players replay the same dice.
4. **Start game**.

During the game the leather tray shows the last throw and its score. Under it: whose turn it is, the turn total, and the buttons:

- **Throw** at the start of your turn;
- **Bank** (with the amount) or **Throw again** after a scoring throw.

Bots play by themselves. Choose their speed (slow, normal, fast), **Pause**, and step through with **Next throw**. The **Recent turns** list shows every throw, and for bots why they banked or carried on (for example, "turn total 20 below threshold 30").

When the game ends, the winner is shown and the game is saved with your runs ("See it in Analyse"). **End this game** stops early and saves it as abandoned. If you leave the page during a game, **Unfinished games** on the Play page lets you resume it, as long as the server has not been restarted.

---

## 5. Simulate

1. **Players**: one to six bots, each with a strategy. The same strategy may play in several seats.
2. **Run**:
   - **Games**: how many to play.
   - **Name**: optional; the strategies' names are used otherwise.
   - **Detail kept**: *Totals only* (final scores, turns, throws and wins per player: enough for every summary figure), *Every turn*, or *Every throw*. *Automatic* keeps every throw up to 10,000 games and totals above. More detail means bigger files and more to analyse: see [storage sizes](#storage-sizes).
   - **Seed**: optional. A run with the same seed, players, rules and software version gives the same games, whatever the number of processes.
   - **Processes**: how many games run in parallel (default: all your processor cores).
3. **Rules**: as for Play.
4. **Start simulation**.

The progress bar shows games played, speed and time left. **Cancel run** stops it and keeps the games already played. When it finishes, the results table appears, with **Open in Analyse** and downloads.

You can leave the page while a run continues; Simulate lists runs in progress when you come back.

---

## 6. Strategies

A strategy decides, after each scoring throw, whether a bot banks or throws again. Five types are available:

| Type | Settings | Banks when |
| --- | --- | --- |
| Fixed stopping threshold | *Bank at* | the turn total reaches the threshold |
| Maximum number of throws | *Throws per turn* | that many throws have been made this turn |
| Combined conditions | *Points to bank*, *Throws to bank*, *Combine conditions with* (or / and) | either condition holds (or), or both do (and) |
| Random decision | *Chance of continuing* | a random draw says so (for example, continues 75% of the time) |
| Game-state-dependent | *When ahead, bank at*; *When behind or tied, bank at*; *Close to winning within*; *When close to winning, bank at* | depends on the position: a conservative threshold when strictly ahead, an aggressive one when behind or tied, and a third (or "never bank": leave it empty) when the player needs that many points or fewer to win |

Six ready-made strategies are included. **New strategy** creates one; choosing a strategy shows its settings.

- **Editing saves a new version.** Runs keep the exact version they used, so results never change after the fact. Version history is listed under the form.
- **Delete** removes a strategy that no stored result uses. A strategy that has results is **archived** instead: hidden from the library and the player lists, still shown in its results. *Show archived* lists them, with **Restore**.

---

## 7. Analyse

The list shows every simulation and played game (filter: All, Simulations, Played games). Click a name to see one run; tick several to compare them.

### One run

- **Summary**: the run's settings (games, rules, dice, scores, seed, detail kept, software version), each player's strategy and parameters, and per player:
  - **win rate** and its **95% interval** (a shared win counts as a fraction);
  - how often the player **reached** the target;
  - **turns to reach the target**: mean, median, minimum, maximum and standard deviation;
  - **points per turn**, **throws per turn**, and **turns lost** (turns ending in 0 or a penalty).

  Charts show the win rate, points per turn, and win rate by **playing position** (does moving first help?). Single-player runs show the distribution of turns to target instead of win rates.
- **Distributions**: turns to reach the target, final scores, game length.
- **Turns** (runs kept at *Every turn* or *Every throw*): how turns end, turn scores, throws per turn.
- **Throws** (*Every throw*): how often each face came up and how often each throw score occurred, against their exact probabilities, with a chi-squared test on the faces. This checks the dice.
- **Games**: every game, filtered by winner and sorted by order, length or closest finish. Click a game for its turn-by-turn record: dice, scores, decisions, and for played games the bots' reasons.

Every chart has a **Table** button with the same numbers.

### Definitions

- **Win rate**: 1 for a sole win, 1/n each for an n-way shared win, averaged over games. The 95% interval is the Wilson score interval.
- **Turns to reach the target** counts only the games in which the player reached it. In multiplayer games that is usually only the winner, so the figure is lower than the same strategy's single-player figure.
- **Per-turn figures** are totals divided by total turns.

### Comparing runs

The table shows each strategy's results in each run (win rate with interval, mean turns to the target, points per turn), with charts of the same. A strategy's results depend on its opponents, so results from different runs are never added together.

### Downloads and deleting

**Download Parquet** or **Download CSV** gives a zip with one file per table for that run. **Delete run** removes a run and its games (strategy versions are kept).

---

## 8. The command line

Everything except interactive play also works from a terminal, without the browser.

| Command | Does |
| --- | --- |
| `ambiciosa simulate run.yaml` | run a simulation described in a YAML file |
| `ambiciosa runs` | list stored runs |
| `ambiciosa summary 3f2a` | headline results of a run (any unique start of its id) |
| `ambiciosa export 3f2a --out exports/ --format parquet` | one Parquet or CSV file per table |
| `ambiciosa presets` | the ready-made strategies |
| `ambiciosa benchmark` | games per second on this computer |
| `ambiciosa validate` | simulated games against exact results (section 10) |
| `ambiciosa serve` | the web app |

`--db PATH` before the command chooses the database file. `simulate` also takes `--games`, `--seed`, `--workers`, `--record-level` and `--name`, which override the file. Ctrl+C cancels a simulation and keeps the games already played.

### A simulation file

```yaml
name: Cautious vs bold
n_games: 100000
master_seed: 42              # optional; a random seed is chosen and stored if omitted
record_level: summary        # optional: summary, turns or full
target: 1000                 # the rules, all optional
end_rule: first_to_target    # or equal_turns
max_turns: 500
face_weights: [1, 1, 1, 1, 1, 1]   # order 9, 10, J, Q, K, A
scoring:                     # optional; any value left out keeps its standard score
  ace: 10
  king: 5
  three_aces: 100
  three_kings: 50
  three_tens: -100
  three_nines: -300
players:
  - Stop at 30                                     # a ready-made strategy, by name
  - name: Bold                                     # a strategy written out
    strategy: {type: threshold, params: {threshold: 60}}
```

Write one player per line, as above. In a one-line list, a comma splits names, so `[Stop at 30, Safe ahead, bold behind]` reads as three players; quote such a name (`"Safe ahead, bold behind"`) if you use that form.

Strategy types and their settings: `threshold` (`threshold`), `max_throws` (`max_throws`), `combined` (`threshold`, `max_throws`, `logic`: `or`/`and`), `random` (`p_continue`), `game_state` (`leading_threshold`, `trailing_threshold`, `close_to_win_points`, `close_threshold`). A strategy written in the file is added to your library; running the same file again reuses it, and changed settings under the same name become a new version.

### Running simulations from Python

```python
from ambiciosa.persistence import Database, strategy_summary
from ambiciosa.simulation import SimulationConfig, SimulationRunner

if __name__ == "__main__":          # required: worker processes re-import this script
    db = Database("ambiciosa.duckdb")
    config = SimulationConfig(n_games=50_000, master_seed=7, players=["Stop at 30", "Stop at 50"])
    result = SimulationRunner(db).run(config)
    print(strategy_summary(db, result.simulation_id))
```

Keep simulation code under `if __name__ == "__main__":` in scripts, and run them from a file (not pasted into `python`). Jupyter notebooks need nothing extra. With `workers=1` everything runs in one process.

---

## 9. Your data: the database, R and exports

All results live in one DuckDB file (`ambiciosa.duckdb` by default). Its tables:

| Table | One row per |
| --- | --- |
| `simulation` | run (including each played game): settings, seed, status, software version |
| `strategy` | strategy version: name, type, parameters |
| `game` | game: index, status, rounds, duration |
| `game_player` | player in a game: seat, playing position, strategy version, final score, winner, turns, throws, turns lost |
| `turn` | turn (runs kept at *Every turn* or *Every throw*) |
| `throw` | throw (runs kept at *Every throw*): the three dice (codes 0–5 for 9, 10, J, Q, K, A), score, decision, and for played games the bot's reason |

Two views join them for analysis: `v_player_results` (one row per player per game, with win share and per-turn figures) and `v_strategy_summary` (one row per run and seat).

### Reading it from R

DuckDB allows one program at a time to write a file. **Stop `ambiciosa serve`** (or any running simulation) before opening the file from R, or open it read-only:

```r
install.packages("duckdb")          # once
library(DBI)
con <- dbConnect(duckdb::duckdb(), "ambiciosa.duckdb", read_only = TRUE)

dbGetQuery(con, "SELECT simulation_id, name, n_games_completed FROM simulation ORDER BY created_at")
summary <- dbGetQuery(con, "SELECT * FROM v_strategy_summary")
turns <- dbGetQuery(con, "
  SELECT strategy_name, turns_taken
  FROM v_player_results
  WHERE simulation_id = '...' AND final_score >= 1000")

dbDisconnect(con, shutdown = TRUE)
```

Or work from exports: `arrow::read_parquet("exports/game_player.parquet")`.

### Storage sizes

Two-player games between threshold strategies last about 100 rounds. Measured with this release:

| Detail kept | Rows per million games | File size per million games |
| --- | --- | --- |
| Totals only | 2 million `game_player` rows | about 0.4 GB |
| Every turn | + about 200 million `turn` rows | about 1.6 GB |
| Every throw | + about 500 million `throw` rows | several GB |

Finding one game's turns among 20 million rows takes about 15 ms, and a full analysis of a 100,000-game run with every turn kept takes about a second.

---

## 10. Correctness and speed

### Validation

`ambiciosa validate` checks the simulator against **exact results computed independently of the game engine**: for single-player games, an exact Markov-chain model of the rules gives the full distribution of turns to reach the target and of each turn's outcome. Nine configurations (every strategy type, loaded dice, changed scores, a short game with a tight turn limit) are each simulated (20,000 games by default) and compared on 7 to 8 figures: mean, median, spread and whole distribution of turns to target, games stopped at the turn limit, mean turn score, share of turns scoring nothing, and throws per turn.

The release was validated with 20,000 games per configuration: **72 of 72 checks passed** (`docs/VALIDATION.md`). Across all comparisons the z-scores had mean −0.11 and spread 1.08, as expected of a correct simulator. Run it yourself:

```bash
ambiciosa validate                         # about 3 minutes on two cores
ambiciosa validate --report my-report.md   # with a full report
```

The automated tests (over 600, run with `pytest`) also check every one of the 216 possible throws against the scoring rules, every rule of turns and games, every strategy decision, reproducibility with any number of processes, storage and retrieval of every table, every metric shown in Analyse against an independent calculation, and the web app in a real browser.

### Speed

`ambiciosa benchmark` measures your computer. On the 2-core machine used for development (two-player games, about 500 throws each):

| Detail kept | 1 process | 2 processes |
| --- | --- | --- |
| Totals only | about 600 games/s | about 1,220 games/s |
| Every turn | about 550 games/s | about 1,070 games/s |
| Every throw | about 420 games/s | about 740 games/s |

Speed grows almost in proportion to processor cores: a million games at *Totals only* takes about 3 to 4 minutes on 8 cores.

---

## 11. Troubleshooting

| Problem | What to do |
| --- | --- |
| `pip install` says it cannot find `pyproject.toml` | You are not in the project folder; `cd` into the folder that contains `pyproject.toml`. |
| `zsh: no matches found: .[dev]` | Keep the quotes: `pip install -e ".[dev]"`. |
| PowerShell: *running scripts is disabled* | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again. |
| `ambiciosa: command not found` | Activate the environment (`.venv\Scripts\Activate.ps1` or `source .venv/bin/activate`), or use `uv run ambiciosa`. |
| *address already in use* on start | Another program uses port 8000: `ambiciosa serve --port 8080`. |
| *Could not set lock on file* / database is locked | Another program (a running `ambiciosa serve`, a simulation, R) has the file open for writing. Stop it, or open the file read-only. |
| A Python script's simulation fails with *worker processes could not start* | Put the simulation code under `if __name__ == "__main__":` and run the script from a file, or use `workers=1`. |
| A YAML file reports an unknown preset made of half a name | A comma split the name in a one-line list; write one player per line or quote the name. |
| An interactive game disappeared after restarting the server | Games in progress live in the server's memory; they are recorded as cancelled when it restarts. Finished games are always saved. |
| The browser tests are skipped | They need Chromium for Playwright: `playwright install chromium`. |

---

## 12. For developers

```text
ambiciosa/engine/       dice, scoring, decision context, turn and game state machine
ambiciosa/strategies/   strategy protocol and registry, five strategy types, versioned specs, presets
ambiciosa/simulation/   seeds, configs (YAML), recorder, parallel runner, command line
ambiciosa/persistence/  schema.sql, writer, queries, export
ambiciosa/analysis/     run metrics, distributions, comparisons (in DuckDB)
ambiciosa/validation/   the exact single-player model and the validation suite
ambiciosa/api/          FastAPI app, interactive game sessions, routes
ambiciosa/web_dist/     the built web app (generated)
web/                    React + TypeScript source
tests/                  unit, integration and browser (e2e) tests
docs/                   this guide, the validation report
```

**Tests**

```bash
pytest                          # everything (about 1 minute)
pytest -m "not e2e"             # without the browser tests
pytest -m "not statistical"     # without the Monte Carlo checks
cd web && npm install && npm test    # frontend unit tests
```

**Changing the web app**

```bash
cd web
npm install
npm run dev      # http://localhost:5173, with /api sent to a running `ambiciosa serve`
npm run build    # type-checks, then writes ambiciosa/web_dist
```

**Adding a strategy type.** Write a Pydantic parameters model (subclass `Params`; give each field a `title` and `description`, which the web form uses) and a class with `decide(ctx, rng) -> DecisionResult`, then call `register(StrategyType(...))` and import the module in `ambiciosa/strategies/__init__.py`. The web form is generated from the parameters model, so the frontend needs no change. To include the type in `ambiciosa validate`, add its single-player rule to `ambiciosa/validation/exact.py`.

**Reproducibility.** Each game's random stream is derived from the run's master seed and the game's index (NumPy `SeedSequence`), so the same seed, configuration and software version give identical games on any number of processes. `tests/integration/test_golden_games.py` holds a fingerprint of 200 complete games that any change to the rules or the random streams would alter.

The architecture, rule decisions and phase-by-phase record are in the project's architecture document.
