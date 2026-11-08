"""The `ambiciosa` command line."""

import pytest

from ambiciosa.persistence import Database
from ambiciosa.simulation.cli import main

YAML = """\
name: CLI test
n_games: 25
master_seed: 5
target: 200
workers: 1
players:
  - Stop at 30
  - name: Bold
    strategy: {type: threshold, params: {threshold: 60}}
"""


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "run.yaml"
    cfg.write_text(YAML)
    return cfg, tmp_path / "test.duckdb"


def test_simulate_runs_and_summary(setup, capsys):
    cfg, db = setup
    assert main(["--db", str(db), "simulate", str(cfg), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "CLI test" in out and "status completed · 25 of 25 games" in out and "Bold" in out
    assert main(["--db", str(db), "simulate", str(cfg), "--games", "12", "--seed", "9",
                 "--record-level", "summary", "--name", "Second", "--quiet"]) == 0
    capsys.readouterr()
    with Database(db, read_only=True) as d:
        sims = d.list_simulations()
        assert [(s["name"], s["n_games_completed"], s["master_seed"], str(s["record_level"])) for s in sims] == [
            ("CLI test", 25, 5, "full"), ("Second", 12, 9, "summary")]
        first = str(sims[0]["simulation_id"])
    assert main(["--db", str(db), "runs"]) == 0
    listing = capsys.readouterr().out
    assert first[:8] in listing and "Second" in listing
    assert main(["--db", str(db), "summary", first[:6]]) == 0
    assert "master seed 5" in capsys.readouterr().out


def test_progress_is_written_to_stderr(setup, capsys):
    cfg, db = setup
    assert main(["--db", str(db), "simulate", str(cfg)]) == 0
    err = capsys.readouterr().err
    assert "Simulating 25 games" in err and "25/25 games (100%)" in err


def test_export_command(setup, tmp_path, capsys):
    cfg, db = setup
    main(["--db", str(db), "simulate", str(cfg), "--quiet"])
    capsys.readouterr()
    with Database(db, read_only=True) as d:
        sid = str(d.list_simulations()[0]["simulation_id"])
    assert main(["--db", str(db), "export", sid[:8], "--out", str(tmp_path / "out"), "--format", "csv"]) == 0
    written = capsys.readouterr().out.split()
    assert len(written) == 6 and all(p.endswith(".csv") for p in written)


def test_database_from_environment(setup, monkeypatch, capsys):
    cfg, db = setup
    monkeypatch.setenv("AMBICIOSA_DB", str(db))
    assert main(["simulate", str(cfg), "--quiet"]) == 0
    assert db.exists()


def test_errors_are_reported_without_tracebacks(setup, tmp_path, capsys):
    cfg, db = setup
    bad = tmp_path / "bad.yaml"
    bad.write_text("n_games: 0\nplayers: [Stop at 30]\n")
    assert main(["--db", str(db), "simulate", str(bad)]) == 2
    assert "n_games" in capsys.readouterr().err
    bad.write_text("n_games: 5\nplayers: [Nobody]\n")
    assert main(["--db", str(db), "simulate", str(bad)]) == 2
    assert "unknown preset" in capsys.readouterr().err
    assert main(["--db", str(db), "simulate", str(tmp_path / "missing.yaml")]) == 2
    with pytest.raises(SystemExit, match="no database"):
        main(["--db", str(tmp_path / "none.duckdb"), "runs"])
    main(["--db", str(db), "simulate", str(cfg), "--quiet"])
    with pytest.raises(SystemExit, match="no run matches"):
        main(["--db", str(db), "summary", "zzzz"])


def test_presets_and_version(capsys):
    assert main(["presets"]) == 0
    assert "Safe ahead, bold behind" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "ambiciosa 1.0.0" in capsys.readouterr().out


def test_benchmark_command(capsys):
    assert main(["benchmark", "--games", "20", "--workers", "1", "--levels", "summary,full"]) == 0
    out = capsys.readouterr().out
    assert "Games/s" in out and "full" in out


def test_serve_builds_the_app_and_starts_uvicorn(setup, monkeypatch, capsys):
    import uvicorn
    import webbrowser

    _, db = setup
    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: started.update(app=app, host=host, port=port))
    monkeypatch.setattr(webbrowser, "open", lambda url: started.setdefault("opened", url))
    assert main(["--db", str(db), "serve", "--port", "8123", "--no-browser"]) == 0
    assert (started["host"], started["port"]) == ("127.0.0.1", 8123)
    assert "opened" not in started
    assert started["app"].state.db.path == str(db)
    assert "http://localhost:8123" in capsys.readouterr().err
    started["app"].state.db.close()
