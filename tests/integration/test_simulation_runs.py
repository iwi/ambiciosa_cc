"""The simulation runner: reproducibility, progress, cancellation and failures."""

import threading
import time
import uuid

import pytest

from ambiciosa.persistence import Database
from ambiciosa.simulation import SimulationRunner, play_chunk, replay_game
from ambiciosa.simulation import runner as runner_module
from ambiciosa.simulation.recorder import BatchRecorder


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


# --------------------------------------------------------- reproducibility


def test_replayed_game_matches_its_stored_record(db, make_config, canonical):
    config = make_config(record_level="full")
    p = SimulationRunner(db).run(config)
    stored = canonical(db, p.simulation_id)
    stored_config = db.load_config(p.simulation_id)
    for index in (0, 31, 59):
        rec = BatchRecorder(p.simulation_id, "full")
        rec.add(replay_game(stored_config, index), index)
        for table in ("game_player", "turn", "throw"):
            expected = sorted((index, *row[1:]) for row in rec.rows(table))
            got = [tuple(str(v) if isinstance(v, uuid.UUID) else v for v in r) for r in stored[table] if r[0] == index]
            assert got == expected


def test_replay_rejects_indices_outside_the_run(make_config):
    with pytest.raises(ValueError):
        replay_game(make_config(), 60)


def test_chunk_size_does_not_change_results(db, make_config, canonical):
    a = SimulationRunner(db).run(make_config(chunk_size=1))
    b = SimulationRunner(db).run(make_config(chunk_size=7))
    c = SimulationRunner(db).run(make_config(chunk_size=1000))
    assert canonical(db, a.simulation_id) == canonical(db, b.simulation_id) == canonical(db, c.simulation_id)


def test_different_master_seeds_give_different_games(db, make_config, canonical):
    a = SimulationRunner(db).run(make_config(master_seed=1))
    b = SimulationRunner(db).run(make_config(master_seed=2))
    assert canonical(db, a.simulation_id)["game_player"] != canonical(db, b.simulation_id)["game_player"]


def test_play_chunk_is_independent_of_how_games_are_grouped(make_config):
    config = make_config()
    sid = uuid.uuid4()
    whole = play_chunk(config, sid, 0, 20)
    parts = [play_chunk(config, sid, a, b) for a, b in ((0, 5), (5, 6), (6, 20))]
    for table in whole:
        joined = [row for part in parts for row in part[table].drop_columns(
            ["duration_ms"] if table == "game" else []).to_pylist()]
        assert whole[table].drop_columns(["duration_ms"] if table == "game" else []).to_pylist() == joined


@pytest.mark.multiprocess
def test_same_results_with_1_2_and_8_workers(db, make_config, canonical):
    """Decision 9 and the Phase 1 test plan: identical results for any number of workers."""
    results = []
    for workers in (1, 2, 8):
        p = SimulationRunner(db).run(make_config(n_games=240, workers=workers, chunk_size=25, record_level="full"))
        assert p.status == "completed", p.error
        results.append(canonical(db, p.simulation_id))
    assert results[0] == results[1] == results[2]
    assert len(results[0]["game"]) == 240 and len(results[0]["throw"]) > 240


@pytest.mark.multiprocess
def test_parallel_run_stores_every_game_once(db, make_config):
    p = SimulationRunner(db).run(make_config(n_games=500, workers=2, record_level="summary"))
    assert (p.status, p.games_completed) == ("completed", 500)
    indices = [r["game_index"] for r in db.query(
        "SELECT game_index FROM game WHERE simulation_id = ? ORDER BY 1", [str(p.simulation_id)])]
    assert indices == list(range(500))
    assert db.get_simulation(p.simulation_id)["n_games_completed"] == 500


# ---------------------------------------------------------------- progress


def test_progress_reports_counts_rate_and_eta(db, make_config):
    seen = []
    final = SimulationRunner(db).run(make_config(n_games=40, chunk_size=5), on_progress=seen.append, interval=0.001)
    assert seen[-1] == final
    assert final.done and final.fraction == 1.0 and final.eta_s == 0.0 and final.rate > 0
    counts = [p.games_completed for p in seen]
    assert counts == sorted(counts) and counts[-1] == 40


def test_progress_and_wait_for_a_background_run(db, make_config):
    runner = SimulationRunner(db)
    sid = runner.start(make_config(n_games=30, chunk_size=3))
    first = runner.progress(sid)
    assert first.games_requested == 30 and first.simulation_id == sid
    final = runner.wait(sid, timeout=60)
    assert (final.status, final.games_completed) == ("completed", 30)
    with pytest.raises(KeyError):
        runner.progress(sid.__class__(int=0))


def test_eta_is_unknown_before_any_game():
    from ambiciosa.simulation import Progress
    p = Progress(uuid.uuid4(), "running", 0, 100, 0.0)
    assert p.eta_s is None and p.rate == 0 and not p.done
    assert Progress(uuid.uuid4(), "running", 50, 100, 10.0).eta_s == pytest.approx(10.0)


# ------------------------------------------------------------ cancellation


def test_cancel_keeps_completed_games(db, make_config, monkeypatch):
    runner = SimulationRunner(db)
    calls = []
    real = runner_module.play_chunk

    def play_then_cancel(config, simulation_id, start, stop):
        calls.append((start, stop))
        if len(calls) == 2:
            runner.cancel(simulation_id)       # cancel while the second chunk is being played
        return real(config, simulation_id, start, stop)

    monkeypatch.setattr(runner_module, "play_chunk", play_then_cancel)
    p = runner.run(make_config(n_games=60, chunk_size=10))
    assert (p.status, p.games_completed) == ("cancelled", 20)   # the chunk in progress is finished and kept
    sim = db.get_simulation(p.simulation_id)
    assert (str(sim["status"]), sim["n_games_completed"]) == ("cancelled", 20)
    assert sim["finished_at"] is not None
    assert db.query("SELECT count(*) n FROM game")[0]["n"] == 20
    assert len(calls) == 2


@pytest.mark.multiprocess
def test_cancel_a_parallel_run(db, make_config):
    runner = SimulationRunner(db)
    sid = runner.start(make_config(n_games=20_000, target=1000, workers=2, chunk_size=20, record_level="summary"))
    deadline = time.monotonic() + 120
    while runner.progress(sid).games_completed == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.cancel(sid)
    p = runner.wait(sid, timeout=120)
    assert p.status == "cancelled" and 0 < p.games_completed < 20_000
    assert p.games_completed % 20 == 0                       # whole chunks only
    stored = db.query("SELECT count(*) n FROM game WHERE simulation_id = ?", [str(sid)])[0]["n"]
    assert stored == p.games_completed == db.get_simulation(sid)["n_games_completed"]


def test_ctrl_c_during_run_cancels(db, make_config, monkeypatch):
    runner = SimulationRunner(db)
    original_wait = threading.Event.wait
    interrupted = []

    def wait(self, timeout=None):
        if timeout is not None and not interrupted:   # the progress loop's first wait
            interrupted.append(True)
            raise KeyboardInterrupt
        return original_wait(self, timeout)

    monkeypatch.setattr(threading.Event, "wait", wait)
    p = runner.run(make_config(n_games=600, chunk_size=10))
    assert p.status in ("cancelled", "completed") and p.done
    assert db.query("SELECT count(*) n FROM game")[0]["n"] == p.games_completed


# ---------------------------------------------------------------- failures


def test_failure_is_recorded_and_completed_games_kept(db, make_config, monkeypatch):
    real = runner_module.play_chunk
    calls = []

    def fail_second(config, simulation_id, start, stop):
        calls.append(start)
        if len(calls) == 2:
            raise RuntimeError("worker exploded")
        return real(config, simulation_id, start, stop)

    monkeypatch.setattr(runner_module, "play_chunk", fail_second)
    p = SimulationRunner(db).run(make_config(n_games=80, chunk_size=10))  # 8 chunks of 10
    assert p.status == "failed" and "worker exploded" in p.error
    assert p.games_completed == 10
    sim = db.get_simulation(p.simulation_id)
    assert (str(sim["status"]), sim["n_games_completed"]) == ("failed", 10)


@pytest.mark.multiprocess
def test_failure_in_a_worker_process(db, make_config):
    # Monkeypatching cannot reach spawned workers, so hand the pool a config
    # that passes the parent's checks but makes every worker raise.
    from ambiciosa.simulation import SimulationConfig

    config = make_config(n_games=40, workers=2, chunk_size=5)
    broken = SimulationConfig.model_construct(**{**dict(config), "record_level": "nonsense"})
    runner = SimulationRunner(db)
    sid = uuid.uuid4()
    db.create_simulation(sid, name="broken", master_seed=1, n_games_requested=40, record_level="full", config={})
    run = runner_module._Run(broken, sid)
    runner._runs[sid] = run
    runner._execute(run)                                    # synchronously, in this thread
    p = runner.progress(sid)
    assert p.status == "failed" and "record_level" in p.error and p.games_completed == 0
    assert str(db.get_simulation(sid)["status"]) == "failed"


# ------------------------------------------------------------- statistics


@pytest.mark.statistical
def test_identical_strategies_win_equally_often(db, make_config):
    """Play order is randomised per game, so two identical bots should each win about half."""
    p = SimulationRunner(db).run(make_config(n_games=4000, target=300, players=["Stop at 30", "Stop at 30"],
                                             record_level="summary"))
    from ambiciosa.persistence import strategy_summary
    rates = [r["win_rate"] for r in strategy_summary(db, p.simulation_id)]
    assert rates[0] + rates[1] == pytest.approx(1.0)
    assert abs(rates[0] - 0.5) < 0.03          # about 3.8 standard errors
    first_movers = db.query(
        "SELECT avg(play_order) m FROM game_player JOIN game USING (game_id) WHERE seat = 0 AND simulation_id = ?",
        [str(p.simulation_id)])[0]["m"]
    assert abs(first_movers - 0.5) < 0.03
