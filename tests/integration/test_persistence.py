"""DuckDB persistence: schema, strategy versions, round-trips, views and export."""

import uuid

import duckdb
import pytest

from ambiciosa import __version__
from ambiciosa.persistence import (
    Database,
    StrategyConflict,
    export_simulations,
    game_by_index,
    game_history,
    run_overview,
    strategy_summary,
)
from ambiciosa.persistence.writer import SCHEMA_VERSION
from ambiciosa.simulation import SimulationRunner, replay_game
from ambiciosa.strategies import PRESETS, StrategySpec


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


def run(db, config):
    p = SimulationRunner(db).run(config)
    assert p.status == "completed", p.error
    return p.simulation_id


# ------------------------------------------------------------------ schema


def test_schema_creates_every_table_and_view(db):
    names = {r[0] for r in db.conn.execute("SHOW TABLES").fetchall()}
    assert {"strategy", "simulation", "game", "game_player", "turn", "throw",
            "v_player_results", "v_strategy_summary", "schema_version"} <= names
    assert db.query("SELECT version FROM schema_version") == [{"version": SCHEMA_VERSION}]


def test_reopening_a_file_keeps_data_and_schema(tmp_path, make_config):
    path = tmp_path / "a.duckdb"
    with Database(path) as d:
        sid = run(d, make_config(n_games=5))
    with Database(path) as d:                       # schema applied again: no error, no duplicates
        assert d.get_simulation(sid)["n_games_completed"] == 5
        assert len(d.query("SELECT * FROM schema_version")) == 1
    with Database(path, read_only=True) as d:
        assert len(d.list_simulations()) == 1


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "new.duckdb"
    with Database(path) as d:
        d.conn.execute("INSERT INTO schema_version VALUES (?, now())", [SCHEMA_VERSION + 1])
    with pytest.raises(RuntimeError, match="schema version"):
        Database(path)


# ------------------------------------------------------- strategy versions


def test_new_strategy_is_stored_as_given(db):
    spec = StrategySpec.create("Mine", "threshold", {"threshold": 45})
    assert db.resolve_strategy(spec) == spec
    assert db.get_strategy(spec.strategy_version_id) == spec


def test_same_version_and_same_content_are_reused(db):
    first = db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 45}))
    again = db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 45}))  # new random ids
    assert again == first
    assert db.resolve_strategy(PRESETS[0]) == db.resolve_strategy(PRESETS[0]) == PRESETS[0]
    assert len(db.list_strategies()) == 2


def test_changed_parameters_make_a_new_version(db):
    v1 = db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 45}))
    v2 = db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 55}))
    assert (v2.strategy_id, v2.version) == (v1.strategy_id, 2)
    explicit = db.resolve_strategy(v2.new_version(params={"threshold": 65}))
    assert (explicit.strategy_id, explicit.version) == (v1.strategy_id, 3)
    assert [s.version for s in db.list_strategies(latest_only=True)] == [3]
    assert db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 45})) == v1


def test_version_ids_are_immutable(db):
    spec = db.resolve_strategy(StrategySpec.create("Mine", "threshold", {"threshold": 45}))
    tampered = StrategySpec.model_validate({**spec.model_dump(), "params": {"threshold": 46}})
    with pytest.raises(StrategyConflict):
        db.resolve_strategy(tampered)


def test_unknown_strategy_version(db):
    with pytest.raises(KeyError):
        db.get_strategy(uuid.uuid4())


# ------------------------------------------------------------ round trips


@pytest.mark.parametrize("level, tables", [
    ("summary", {"game", "game_player"}),
    ("turns", {"game", "game_player", "turn"}),
    ("full", {"game", "game_player", "turn", "throw"}),
])
def test_round_trip_at_each_level(db, make_config, canonical, level, tables):
    config = make_config(record_level=level)
    sid = run(db, config)
    sim = db.get_simulation(sid)
    assert (sim["status"], sim["n_games_completed"], sim["record_level"]) == ("completed", 60, level)
    assert sim["software_version"] == __version__ and sim["finished_at"] is not None
    rows = canonical(db, sid)
    assert {t for t, r in rows.items() if r} == tables

    stored_config = db.load_config(sid)
    for index in (0, 17, 59):
        game = replay_game(stored_config, index)
        stored = game_by_index(db, sid, index)
        history = game_history(db, stored["game_id"])
        players = history["players"]
        assert [p["final_score"] for p in players] == list(game.scores())
        assert [p["seat"] for p in players if p["is_winner"]] == list(game.winners)
        assert [p["play_order"] for p in sorted(players, key=lambda p: p["play_order"])] == list(range(3))
        assert sorted(players, key=lambda p: p["play_order"])[0]["seat"] == game.play_order[0]
        if level == "summary":
            assert history["turns"] == []
            continue
        expected_turns = [(t.seat, t.turn_number, t.turn_score, t.banked_after, t.end_reason.value) for t in game.history]
        got_turns = [(t["seat"], t["turn_number"], t["turn_score"], t["banked_after"], str(t["end_reason"]))
                     for t in history["turns"]]
        assert got_turns == expected_turns
        if level == "full":
            for t_game, t_db in zip(game.history, history["turns"], strict=True):
                assert [(r.dice, r.score, r.decision.value if r.decision else None) for r in t_game.throws] == [
                    ((th["die1"], th["die2"], th["die3"]), th["throw_score"], th["decision"] and str(th["decision"]))
                    for th in t_db["throws"]
                ]


def test_stored_config_points_at_strategy_versions(db, make_config):
    sid = run(db, make_config())
    stored = db.get_simulation(sid)["config"]
    assert [p["name"] for p in stored["players"]] == ["Stop at 30", "Coin flip 75%", "Bold"]
    used = {str(r["strategy_version_id"]) for r in db.query("SELECT DISTINCT strategy_version_id FROM game_player")}
    assert used == {p["strategy_version_id"] for p in stored["players"]}


def test_running_the_same_config_twice_reuses_strategies(db, make_config):
    run(db, make_config())
    run(db, make_config())
    assert len(db.list_strategies()) == 3
    assert len(db.list_simulations()) == 2


def test_delete_simulation_removes_its_games_only(db, make_config):
    keep = run(db, make_config(n_games=5))
    drop = run(db, make_config(n_games=7))
    db.delete_simulation(drop)
    assert [r["simulation_id"] for r in db.list_simulations()] == [keep]
    assert db.query("SELECT count(*) n FROM game")[0]["n"] == 5
    for table in ("game_player", "turn", "throw"):
        orphans = db.query(f"SELECT count(*) n FROM {table} WHERE game_id NOT IN (SELECT game_id FROM game)")
        assert orphans[0]["n"] == 0
    assert len(db.list_strategies()) == 3


def test_failed_batch_leaves_nothing_behind(db, make_config):
    sid = run(db, make_config(n_games=3))
    from ambiciosa.simulation import play_chunk
    tables = play_chunk(db.load_config(sid), sid, 0, 3)          # same game ids again: primary key clash
    with pytest.raises(duckdb.ConstraintException):
        db.insert_batch(sid, tables)
    assert db.get_simulation(sid)["n_games_completed"] == 3
    assert db.query("SELECT count(*) n FROM game")[0]["n"] == 3
    db.insert_batch(sid, play_chunk(db.load_config(sid), sid, 3, 4))  # the connection is still usable
    assert db.get_simulation(sid)["n_games_completed"] == 4


# ------------------------------------------------------------------- views


def test_win_share_counts_shared_wins_as_fractions(db, make_config):
    # Tiny target under equal_turns: several players often pass it in the same round.
    sid = run(db, make_config(n_games=300, target=60, end_rule="equal_turns", record_level="summary"))
    per_game = db.query(
        "SELECT game_id, sum(win_share) s, count(*) FILTER (WHERE is_winner) w FROM v_player_results "
        "WHERE simulation_id = ? GROUP BY game_id", [str(sid)])
    assert all(r["s"] == pytest.approx(1.0) for r in per_game)
    assert any(r["w"] > 1 for r in per_game), "expected at least one shared win"
    assert run_overview(db, sid)["shared_wins"] == sum(r["w"] > 1 for r in per_game)
    total = sum(r["wins"] for r in strategy_summary(db, sid))
    assert total == pytest.approx(300)


def test_strategy_summary_matches_an_independent_calculation(db, make_config):
    sid = run(db, make_config(n_games=200, record_level="summary"))
    rows = db.query("SELECT seat, final_score, turns_taken, total_throws, busts, is_winner FROM game_player "
                    "JOIN game USING (game_id) WHERE simulation_id = ?", [str(sid)])
    summary = {r["seat"]: r for r in strategy_summary(db, sid)}
    for seat in range(3):
        mine = [r for r in rows if r["seat"] == seat]
        turns = sum(r["turns_taken"] for r in mine)
        s = summary[seat]
        assert s["games"] == 200
        assert s["points_per_turn"] == pytest.approx(sum(r["final_score"] for r in mine) / turns)
        assert s["throws_per_turn"] == pytest.approx(sum(r["total_throws"] for r in mine) / turns)
        assert s["bust_rate"] == pytest.approx(sum(r["busts"] for r in mine) / turns)
        winners = [r["turns_taken"] for r in mine if r["is_winner"]]
        assert s["mean_turns_to_win"] == pytest.approx(sum(winners) / len(winners))
        assert s["wins"] == len(winners)                      # first_to_target: no shared wins
    assert run_overview(db, sid)["finished"] == 200


def test_unfinished_games_have_no_winner(db, make_config):
    sid = run(db, make_config(n_games=10, target=10**6, max_turns=4, record_level="summary"))
    ov = run_overview(db, sid)
    assert (ov["finished"], ov["unfinished"], ov["mean_rounds"]) == (0, 10, 4)
    assert all(r["wins"] == 0 for r in strategy_summary(db, sid))


# ------------------------------------------------------------------ export


def _table_rows(db, table, sid):
    if table in ("simulation", "game"):
        sql = f"SELECT * FROM {table} WHERE simulation_id = ? ORDER BY ALL"
    elif table == "strategy":
        sql = ("SELECT * FROM strategy WHERE strategy_version_id IN (SELECT strategy_version_id FROM game_player "
               "JOIN game USING (game_id) WHERE simulation_id = ?) ORDER BY ALL")
    else:
        sql = f"SELECT x.* FROM {table} x JOIN game USING (game_id) WHERE simulation_id = ? ORDER BY ALL"
    return db.conn.execute(sql, [str(sid)]).fetchall()


def test_parquet_export_reloads_identically(db, make_config, tmp_path):
    sid = run(db, make_config())
    other = run(db, make_config(n_games=4, master_seed=1))          # must not leak into the export
    files = export_simulations(db, [sid], tmp_path)
    assert [f.name for f in files] == [f"{t}.parquet" for t in
                                       ("simulation", "strategy", "game", "game_player", "turn", "throw")]
    for f in files:
        table = f.stem
        reloaded = db.conn.execute(f"SELECT * FROM read_parquet('{f}') ORDER BY ALL").fetchall()
        original = _table_rows(db, table, sid)
        if table in ("simulation", "game"):
            # Enum columns come back as text; compare as text.
            reloaded = [tuple(str(v) if isinstance(v, str) else v for v in r) for r in reloaded]
        assert len(reloaded) == len(original) and len(original) > 0
        assert [tuple(map(str, r)) for r in reloaded] == [tuple(map(str, r)) for r in original]
    assert str(other) not in (tmp_path / "simulation.parquet").read_bytes().decode("latin-1")


def test_csv_export_reloads_identically(db, make_config, tmp_path):
    sid = run(db, make_config(record_level="turns"))
    files = export_simulations(db, [sid], tmp_path, "csv")
    assert {f.stem for f in files} == {"simulation", "strategy", "game", "game_player", "turn"}  # no throws at 'turns'
    for f in files:
        reloaded = db.conn.execute(f"SELECT * FROM read_csv('{f}', all_varchar=true)").fetchall()
        original = _table_rows(db, f.stem, sid)
        assert len(reloaded) == len(original)
        if f.stem in ("game_player", "turn"):  # plain numbers and ids: identical as text
            def text(v):
                return None if v is None else str(v).lower() if isinstance(v, bool) else str(v)
            assert sorted(reloaded) == sorted(tuple(text(v) for v in r) for r in original)


def test_export_of_several_runs_and_errors(db, make_config, tmp_path):
    a = run(db, make_config(n_games=3))
    b = run(db, make_config(n_games=4, master_seed=2))
    export_simulations(db, [a, str(b)], tmp_path)
    n = db.conn.execute(f"SELECT count(*) FROM read_parquet('{tmp_path / 'game.parquet'}')").fetchone()[0]
    assert n == 7
    with pytest.raises(KeyError):
        export_simulations(db, [uuid.uuid4()], tmp_path)
    with pytest.raises(ValueError):
        export_simulations(db, [a], tmp_path, "xlsx")
    with pytest.raises(ValueError):
        export_simulations(db, [], tmp_path)
    files = export_simulations(db, [a], tmp_path / "empty", include_empty=True, fmt="parquet")
    assert len(files) == 6


def test_upgrade_to_version_3_drops_detail_keys_and_keeps_rows(tmp_path, make_config, canonical):
    """A version-2 file (keyed turn and throw tables) is rebuilt without the keys, rows intact."""
    path = tmp_path / "v2.duckdb"
    with Database(path) as d:
        sid = SimulationRunner(d).run(make_config(n_games=20, record_level="full")).simulation_id
        before = canonical(d, sid)
        for table, key in (("turn", "game_id, seat, turn_number"), ("throw", "game_id, seat, turn_number, throw_number")):
            cols = d.conn.execute(f"SELECT sql FROM duckdb_tables() WHERE table_name = '{table}'").fetchone()[0]
            keyed = cols.rstrip().rstrip(");") + f", PRIMARY KEY ({key}));"
            d.conn.execute(f"CREATE TABLE {table}_old AS SELECT * FROM {table}")
            d.conn.execute(f"DROP TABLE {table}")
            d.conn.execute(keyed)
            d.conn.execute(f"INSERT INTO {table} SELECT * FROM {table}_old")
            d.conn.execute(f"DROP TABLE {table}_old")
        d.conn.execute("DELETE FROM schema_version")
        d.conn.execute("INSERT INTO schema_version VALUES (2, now())")
        assert d.query("SELECT count(*) n FROM duckdb_constraints() WHERE table_name IN ('turn', 'throw') "
                       "AND constraint_type = 'PRIMARY KEY'")[0]["n"] == 2
    with Database(path) as d:
        assert max(r["version"] for r in d.query("SELECT version FROM schema_version")) == SCHEMA_VERSION == 3
        assert d.query("SELECT count(*) n FROM duckdb_constraints() WHERE table_name IN ('turn', 'throw') "
                       "AND constraint_type = 'PRIMARY KEY'")[0]["n"] == 0
        assert canonical(d, sid) == before
        SimulationRunner(d).run(make_config(n_games=5, record_level="full"))   # still writable


def test_detail_rows_stay_unique_without_keys(db, make_config):
    """The game table's key still stops a batch being stored twice, so turns and throws cannot duplicate."""
    sid = run(db, make_config(n_games=3, record_level="full"))
    from ambiciosa.simulation import play_chunk
    before = db.query("SELECT count(*) n FROM throw")[0]["n"]
    with pytest.raises(duckdb.ConstraintException):
        db.insert_batch(sid, play_chunk(db.load_config(sid), sid, 0, 3))
    assert db.query("SELECT count(*) n FROM throw")[0]["n"] == before
    dupes = db.query("SELECT count(*) n FROM (SELECT game_id, seat, turn_number, throw_number FROM throw "
                     "GROUP BY ALL HAVING count(*) > 1)")[0]["n"]
    assert dupes == 0
