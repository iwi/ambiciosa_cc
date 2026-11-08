"""The complete application, as a user would drive it: command line, database file, web API, validation."""

import io
import subprocess
import sys
import zipfile

from fastapi.testclient import TestClient

from ambiciosa import __version__
from ambiciosa.api import create_app
from ambiciosa.simulation.cli import main

YAML = """\
name: Workflow
n_games: 300
master_seed: 8
target: 300
record_level: full
workers: 2
scoring:
  ace: 15
players:
  - Stop at 30
  - Safe ahead, bold behind
"""


def test_cli_run_then_web_app_on_the_same_file(tmp_path, capsys):
    db_path, cfg = tmp_path / "work.duckdb", tmp_path / "run.yaml"
    cfg.write_text(YAML)
    # 1. A simulation from the command line, in parallel, into a database file.
    assert main(["--db", str(db_path), "simulate", str(cfg), "--quiet"]) == 0
    assert "status completed · 300 of 300 games" in capsys.readouterr().out

    # 2. The web app opens the same file: the run, its analysis and its export are there.
    app = create_app(db_path, static_dir=False)
    with TestClient(app) as c:
        (run,) = c.get("/api/simulations").json()
        assert (run["name"], run["n_games_completed"], run["software_version"]) == ("Workflow", 300, __version__)
        a = c.get(f"/api/simulations/{run['simulation_id']}/analysis").json()
        assert a["simulation"]["scoring"]["ace"] == 15 and a["available"] == {"turns": True, "throws": True}
        assert sum(p["wins"] for p in a["players"]) == 300
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/simulations/{run['simulation_id']}/export").content))
        assert "throw.parquet" in z.namelist()

        # 3. Play a game against a bot in the same app; it lands beside the simulation.
        lib = {s["name"]: s["strategy_version_id"] for s in c.get("/api/strategies").json()}
        g = c.post("/api/games", json={"players": [{"name": "Bot", "strategy_version_id": lib["Stop at 30"]}],
                                       "target": 100, "seed": 1}).json()
        while c.get(f"/api/games/{g['game_id']}").json()["awaiting"] != "finished":
            c.post(f"/api/games/{g['game_id']}/throw")
        assert {r["source"] for r in c.get("/api/simulations").json()} == {"simulation", "interactive"}
    app.state.db.close()

    # 4. The command line sees both runs afterwards.
    assert main(["--db", str(db_path), "runs"]) == 0
    listing = capsys.readouterr().out
    assert "Workflow" in listing and "interactive" in listing


def test_python_dash_m_entry_point():
    out = subprocess.run([sys.executable, "-m", "ambiciosa", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"ambiciosa {__version__}"
