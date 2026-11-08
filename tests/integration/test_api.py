"""The HTTP API, through FastAPI's test client."""

import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

from ambiciosa.api import create_app, seed_presets
from ambiciosa.persistence import Database
from ambiciosa.strategies import PRESETS


@pytest.fixture
def client():
    app = create_app(":memory:", static_dir=False)
    with TestClient(app) as c:
        yield c


def library(client):
    return {s["name"]: s for s in client.get("/api/strategies").json()}


def vid(client, name):
    return library(client)[name]["strategy_version_id"]


def play_to_end(client, game_id, stop_at=20):
    """Drive a game: throw whenever asked, the human stops at `stop_at` turn points."""
    for _ in range(10_000):
        st = client.get(f"/api/games/{game_id}").json()
        if st["awaiting"] == "finished":
            return st
        if st["awaiting"] == "throw":
            assert client.post(f"/api/games/{game_id}/throw").status_code == 200
        else:
            d = "STOP" if st["current_turn"]["points"] >= stop_at else "CONTINUE"
            assert client.post(f"/api/games/{game_id}/decision", json={"decision": d}).status_code == 200
    raise AssertionError("game did not end")


# ------------------------------------------------------------- info, types


def test_info_and_presets_seeded(client):
    info = client.get("/api/info").json()
    assert info["version"] and info["cpu_count"] >= 1
    assert set(library(client)) == {p.name for p in PRESETS}


def test_presets_are_seeded_only_into_an_empty_library():
    db = Database(":memory:")
    assert seed_presets(db) == 6
    assert seed_presets(db) == 0


def test_strategy_types_carry_json_schemas(client):
    types = client.get("/api/strategy-types").json()
    assert [t["name"] for t in types] == ["threshold", "max_throws", "combined", "random", "game_state"]
    threshold = types[0]["schema"]
    assert threshold["properties"]["threshold"]["type"] == "integer"
    assert all(t["title"] and t["description"] for t in types)


# -------------------------------------------------------------- strategies


def test_create_edit_and_version_a_strategy(client):
    r = client.post("/api/strategies", json={"name": "Stop at 40", "type": "threshold", "params": {"threshold": 40}})
    assert r.status_code == 201
    created = r.json()
    assert (created["version"], created["n_versions"], created["params"]) == (1, 1, {"threshold": 40})
    sid = created["strategy_id"]

    assert client.post("/api/strategies", json={"name": "stop at 40", "type": "threshold"}).status_code == 409

    v2 = client.put(f"/api/strategies/{sid}", json={"params": {"threshold": 45}, "description": "a bit bolder"}).json()
    assert (v2["version"], v2["strategy_id"], v2["params"]["threshold"]) == (2, sid, 45)
    same = client.put(f"/api/strategies/{sid}", json={"params": {"threshold": 45}}).json()
    assert same["strategy_version_id"] == v2["strategy_version_id"]       # nothing changed: no new version
    back = client.put(f"/api/strategies/{sid}", json={"params": {"threshold": 40}}).json()
    assert back["version"] == 3                                            # going back is still a new version

    versions = client.get(f"/api/strategies/{sid}").json()["versions"]
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert library(client)["Stop at 40"]["version"] == 3

    assert client.put(f"/api/strategies/{sid}", json={"name": "Stop at 30"}).status_code == 409
    renamed = client.put(f"/api/strategies/{sid}", json={"name": "Forty"}).json()
    assert renamed["name"] == "Forty" and renamed["label"] == "Forty (v4)"


def test_invalid_strategies_are_rejected(client):
    assert client.post("/api/strategies", json={"name": "X", "type": "nope"}).status_code == 422
    r = client.post("/api/strategies", json={"name": "X", "type": "threshold", "params": {"threshold": -1}})
    assert r.status_code == 422 and "threshold" in r.json()["detail"]
    r = client.post("/api/strategies", json={"name": "X", "type": "threshold", "params": {"bogus": 1}})
    assert r.status_code == 422
    assert client.put(f"/api/strategies/{uuid.uuid4()}", json={"name": "Y"}).status_code == 404
    assert client.get("/api/strategies/not-a-uuid").status_code == 404


def test_delete_unused_and_archive_used_strategies(client):
    unused = library(client)["Three throws"]["strategy_id"]
    assert client.delete(f"/api/strategies/{unused}").json() == {"result": "deleted"}
    assert "Three throws" not in library(client)
    assert client.get(f"/api/strategies/{unused}").status_code == 404

    used = library(client)["Stop at 30"]
    client.post("/api/simulations", json={"n_games": 3, "workers": 1, "target": 100,
                                          "players": [{"name": "A", "strategy_version_id": used["strategy_version_id"]}]})
    _wait_all(client)
    assert library(client)["Stop at 30"]["has_results"] is True
    assert client.delete(f"/api/strategies/{used['strategy_id']}").json() == {"result": "archived"}
    assert "Stop at 30" not in library(client)
    archived = {s["name"]: s for s in client.get("/api/strategies?include_archived=true").json()}
    assert archived["Stop at 30"]["archived"] is True
    assert client.post(f"/api/strategies/{used['strategy_id']}/restore").json() == {"result": "restored"}
    assert "Stop at 30" in library(client)


# ------------------------------------------------------------------- games


def new_game(client, **extra):
    body = {"players": [{"name": "Ana", "player_type": "human"},
                        {"name": "Bot", "strategy_version_id": vid(client, "Stop at 30")}],
            "target": 150, "seed": 11, **extra}
    r = client.post("/api/games", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_human_vs_bot_game_is_played_and_stored(client):
    g = new_game(client)
    assert g["status"] == "in_progress" and g["awaiting"] == "throw"
    assert [p["player_type"] for p in g["players"]] == ["human", "automated"]
    assert g["players"][1]["strategy"]["name"] == "Stop at 30"
    final = play_to_end(client, g["game_id"])
    assert final["status"] == "finished" and len(final["winners"]) == 1
    assert max(p["score"] for p in final["players"]) >= 150

    runs = client.get("/api/simulations?source=interactive").json()
    assert len(runs) == 1 and runs[0]["status"] == "completed" and runs[0]["n_games_completed"] == 1
    assert client.get("/api/simulations?source=simulation").json() == []

    hist = client.get(f"/api/games/{g['game_id']}/history").json()
    assert hist["game"]["status"] == "finished"
    throws = [t for turn in hist["turns"] for t in turn["throws"]]
    by_seat = {p["seat"]: p for p in hist["players"]}
    bot_reasons = [t["reason"] for t in throws if t["seat"] == 1 and t["decision"]]
    human_reasons = [t["reason"] for t in throws if t["seat"] == 0 and t["decision"]]
    assert bot_reasons and all("threshold" in r for r in bot_reasons)       # decision 10: reasons kept
    assert human_reasons and set(human_reasons) == {"chosen by the player"}
    assert by_seat[0]["strategy_version_id"] is None and by_seat[0]["player_type"] == "human"

    stats = client.get(f"/api/simulations/{runs[0]['simulation_id']}/stats").json()
    assert stats["overview"]["games"] == 1


def test_bot_throw_includes_its_decision(client):
    g = new_game(client, players=[{"name": "Bot", "strategy_version_id": vid(client, "Stop at 50")}])
    for _ in range(200):
        r = client.post(f"/api/games/{g['game_id']}/throw").json()
        ev = r["event"]
        assert ev["seat"] == 0 and len(ev["throw"]["dice"]) == 3 and len(ev["throw"]["symbols"]) == 3
        if ev["bot_decision"]:
            assert ev["bot_decision"]["decision"] in ("CONTINUE", "STOP") and ev["bot_decision"]["reason"]
            assert ev["throw"]["decision"] == ev["bot_decision"]["decision"]
            break
    else:
        raise AssertionError("bot never had to decide")


def test_actions_out_of_turn_are_refused(client):
    g = new_game(client, players=[{"name": "Bot", "strategy_version_id": vid(client, "Stop at 30")},
                                  {"name": "Ana", "player_type": "human"}], seed=4)
    gid = g["game_id"]
    r = client.post(f"/api/games/{gid}/decision", json={"decision": "STOP"})
    assert r.status_code == 409 and "awaiting 'throw'" in r.json()["detail"]
    # Find a moment where the human must decide, then a throw is refused.
    for _ in range(500):
        st = client.get(f"/api/games/{gid}").json()
        if st["awaiting"] == "decision":
            assert st["current_player_type"] == "human"
            assert client.post(f"/api/games/{gid}/throw").status_code == 409
            break
        client.post(f"/api/games/{gid}/throw")
    else:
        raise AssertionError("human never had to decide")
    assert client.post(f"/api/games/{gid}/decision", json={"decision": "MAYBE"}).status_code == 422


def test_abandoned_game_is_stored(client):
    g = new_game(client)
    for _ in range(3):
        st = client.get(f"/api/games/{g['game_id']}").json()
        if st["awaiting"] == "throw":
            client.post(f"/api/games/{g['game_id']}/throw")
        else:
            client.post(f"/api/games/{g['game_id']}/decision", json={"decision": "STOP"})
    st = client.post(f"/api/games/{g['game_id']}/abandon").json()["state"]
    assert st["status"] == "abandoned" and st["awaiting"] == "finished"
    run = client.get("/api/simulations?source=interactive").json()[0]
    assert run["status"] == "cancelled"
    assert client.get(f"/api/games/{g['game_id']}/history").json()["game"]["status"] == "abandoned"
    assert client.post(f"/api/games/{g['game_id']}/throw").status_code == 409
    assert client.post(f"/api/games/{g['game_id']}/abandon").status_code == 200    # idempotent


def test_same_seed_same_game(client):
    a, b = new_game(client, seed=99), new_game(client, seed=99)
    ra = client.post(f"/api/games/{a['game_id']}/throw").json()["event"]["throw"]["dice"]
    rb = client.post(f"/api/games/{b['game_id']}/throw").json()["event"]["throw"]["dice"]
    assert a["play_order"] == b["play_order"] and ra == rb


def test_game_validation(client):
    bad = [
        {"players": []},
        {"players": [{"name": "Bot"}]},                                                     # no strategy
        {"players": [{"name": "Ana", "player_type": "human", "strategy_version_id": vid(client, "Stop at 30")}]},
        {"players": [{"name": "Bot", "strategy_version_id": str(uuid.uuid4())}]},
        {"players": [{"name": "Ana", "player_type": "human"}], "target": 0},
        {"players": [{"name": "Ana", "player_type": "human"}] * 7},
    ]
    for body in bad:
        r = client.post("/api/games", json=body)
        assert r.status_code == 422, body
        assert r.json()["detail"]
    assert client.get(f"/api/games/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/games/{uuid.uuid4()}/history").status_code == 404


def test_list_games_of_this_session(client):
    g = new_game(client)
    assert [x["game_id"] for x in client.get("/api/games").json()] == [g["game_id"]]


# ------------------------------------------------------------- simulations


def _wait_all(client):
    for r in client.get("/api/simulations").json():
        if r["status"] == "running":
            with client.stream("GET", f"/api/simulations/{r['simulation_id']}/progress") as s:
                for _ in s.iter_lines():
                    pass


def start_sim(client, **extra):
    body = {"n_games": 120, "master_seed": 5, "workers": 1, "target": 200, "players": [
        {"name": "Careful", "strategy_version_id": vid(client, "Stop at 30")},
        {"name": "Bold", "strategy_version_id": vid(client, "Stop at 50")}], **extra}
    r = client.post("/api/simulations", json=body)
    assert r.status_code == 201, r.text
    return r.json()["simulation_id"]


def test_simulation_progress_stream_and_results(client):
    sid = start_sim(client)
    with client.stream("GET", f"/api/simulations/{sid}/progress") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    assert events[-1] == {}                                       # the closing `end` event
    last = events[-2]
    assert (last["status"], last["games_completed"], last["fraction"]) == ("completed", 120, 1.0)
    counts = [e["games_completed"] for e in events[:-1]]
    assert counts == sorted(counts)

    detail = client.get(f"/api/simulations/{sid}").json()
    assert detail["status"] == "completed" and detail["config"]["players"][0]["strategy_label"] == "Stop at 30"
    assert detail["progress"]["games_completed"] == 120

    stats = client.get(f"/api/simulations/{sid}/stats").json()
    assert stats["overview"]["games"] == 120
    assert [p["display_name"] for p in stats["players"]] == ["Careful", "Bold"]
    assert sum(p["wins"] for p in stats["players"]) == pytest.approx(120)

    page = client.get(f"/api/simulations/{sid}/games?limit=5&offset=10").json()
    games = page["games"]
    assert page["total"] == 120
    assert [g["game_index"] for g in games] == [10, 11, 12, 13, 14]
    assert all(len(g["scores"]) == 2 and len(g["winners"]) == 1 for g in games)
    hist = client.get(f"/api/games/{games[0]['game_id']}/history").json()
    assert hist["turns"] and all(t["reason"] is None for turn in hist["turns"] for t in turn["throws"])


def test_progress_stream_of_a_finished_run_ends_at_once(client):
    sid = start_sim(client)
    _wait_all(client)
    with client.stream("GET", f"/api/simulations/{sid}/progress") as r:
        events = [line for line in r.iter_lines() if line.startswith("event:")]
    assert events == ["event: progress", "event: end"]


def test_same_seed_through_the_api_gives_same_results(client):
    a, b = start_sim(client), start_sim(client, workers=2)
    _wait_all(client)
    sa = client.get(f"/api/simulations/{a}/stats").json()["players"]
    sb = client.get(f"/api/simulations/{b}/stats").json()["players"]
    assert [(p["wins"], p["points_per_turn"]) for p in sa] == [(p["wins"], p["points_per_turn"]) for p in sb]


def test_cancel_delete_compare_and_export(client):
    a = start_sim(client)
    _wait_all(client)
    assert client.post(f"/api/simulations/{a}/cancel").status_code == 409    # already finished
    b = start_sim(client, master_seed=6, n_games=40)
    _wait_all(client)

    cmp = client.get(f"/api/compare?ids={a},{b}").json()
    assert [c["simulation"]["simulation_id"] for c in cmp["runs"]] == [a, b]
    assert [c["overview"]["games"] for c in cmp["runs"]] == [120, 40]
    assert {s["strategy_name"] for s in cmp["strategies"]} == {"Stop at 30", "Stop at 50"}
    assert all(set(s["cells"]) == {a, b} for s in cmp["strategies"])

    r = client.get(f"/api/simulations/{a}/export?format=parquet")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert set(names) == {f"{t}.parquet" for t in ("simulation", "strategy", "game", "game_player", "turn", "throw")}
    assert client.get(f"/api/simulations/{a}/export?format=xlsx").status_code == 422
    import glob
    import tempfile
    assert not glob.glob(f"{tempfile.gettempdir()}/ambiciosa-export-*"), "temporary export files are removed"
    csv = client.get(f"/api/simulations/{a}/export?format=csv")
    assert csv.headers["content-disposition"].endswith('-csv.zip"')
    assert "game.csv" in zipfile.ZipFile(io.BytesIO(csv.content)).namelist()

    assert client.delete(f"/api/simulations/{b}").json() == {"result": "deleted"}
    assert client.get(f"/api/simulations/{b}").status_code == 404
    assert [r["simulation_id"] for r in client.get("/api/simulations").json()] == [a]


def test_cancel_a_running_simulation(client):
    sid = start_sim(client, n_games=50_000, target=1000, chunk_size=50)
    r = client.post(f"/api/simulations/{sid}/cancel")
    assert r.status_code == 200
    _wait_all(client)
    final = client.get(f"/api/simulations/{sid}").json()
    assert final["status"] == "cancelled" and final["n_games_completed"] < 50_000
    assert client.delete(f"/api/simulations/{sid}").status_code == 200


def test_simulation_validation(client):
    human = {"name": "Ana", "player_type": "human"}
    assert client.post("/api/simulations", json={"n_games": 5, "players": [human]}).status_code == 422
    assert client.post("/api/simulations", json={"n_games": 0, "players": [
        {"name": "A", "strategy_version_id": vid(client, "Stop at 30")}]}).status_code == 422
    assert client.get(f"/api/simulations/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/simulations/{uuid.uuid4()}/progress").status_code == 404
    assert client.get("/api/simulations?source=other").status_code == 422


# --------------------------------------------------------- start-up, files


def test_interrupted_runs_are_marked_failed_on_start(tmp_path):
    path = tmp_path / "x.duckdb"
    with Database(path) as d:
        d.create_simulation(uuid.uuid4(), name="crashed", master_seed=1, n_games_requested=10,
                            record_level="summary", config={})
        d.create_simulation(uuid.uuid4(), name="left mid-game", master_seed=1, n_games_requested=1,
                            record_level="full", config={}, source="interactive")
    app = create_app(path, static_dir=False)
    with TestClient(app) as c:
        assert c.get("/api/info").json()["interrupted_runs_marked_failed"] == 2
        status = {r["name"]: r["status"] for r in c.get("/api/simulations").json()}
        assert status == {"crashed": "failed", "left mid-game": "cancelled"}
    app.state.db.close()


def test_schema_upgrade_from_version_1(tmp_path):
    path = tmp_path / "v1.duckdb"
    with Database(path) as d:                                 # make it look like a version-1 file
        d.conn.execute("DROP TABLE strategy_archive")
        d.conn.execute("DELETE FROM schema_version")
        d.conn.execute("INSERT INTO schema_version VALUES (1, now())")
    with Database(path) as d:
        from ambiciosa.persistence import SCHEMA_VERSION
        assert max(r["version"] for r in d.query("SELECT version FROM schema_version")) == SCHEMA_VERSION
        assert d.query("SELECT count(*) n FROM strategy_archive")[0]["n"] == 0


def test_built_app_is_served_with_client_side_routes(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    with TestClient(create_app(":memory:", static_dir=tmp_path)) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/simulate").text == "<html>app</html>"          # React route
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert c.get("/../pyproject.toml").text == "<html>app</html>"
        assert c.get("/api/nothing").status_code == 404
        assert c.get("/api/docs").status_code == 200


# ---------------------------------------------------------------- analysis


def test_analysis_endpoint(client):
    sid = start_sim(client, record_level="full")
    _wait_all(client)
    a = client.get(f"/api/simulations/{sid}/analysis").json()
    assert a["available"] == {"turns": True, "throws": True}
    assert a["simulation"]["players"][0]["strategy"]["params"] == {"threshold": 30}
    assert [p["seat"] for p in a["players"]] == [0, 1]
    assert {"turns_to_target_min", "turns_to_target_max", "turns_to_target_sd", "win_rate_low"} <= set(a["players"][0])
    assert a["throws"]["n_throws"] > 0 and len(a["throws"]["faces"]) == 6
    json.dumps(a)                                              # plain JSON throughout
    assert client.get(f"/api/simulations/{uuid.uuid4()}/analysis").status_code == 404


def test_games_list_filters_and_sorts(client):
    sid = start_sim(client)
    _wait_all(client)
    url = f"/api/simulations/{sid}/games"
    everything = client.get(f"{url}?limit=1000").json()
    won_by_0 = client.get(f"{url}?winner=0&limit=1000").json()
    won_by_1 = client.get(f"{url}?winner=1&limit=1000").json()
    assert won_by_0["total"] + won_by_1["total"] == everything["total"] == 120
    assert all(0 in g["winner_seats"] for g in won_by_0["games"])
    longest = client.get(f"{url}?sort=longest&limit=5").json()["games"]
    rounds = sorted((g["n_rounds"] for g in everything["games"]), reverse=True)
    assert [g["n_rounds"] for g in longest] == rounds[:5]
    closest = client.get(f"{url}?sort=closest&limit=3").json()["games"]
    margins = sorted(g["margin"] for g in everything["games"])
    assert [g["margin"] for g in closest] == margins[:3]
    assert client.get(f"{url}?status=unfinished").json()["total"] == 0
    assert client.get(f"{url}?sort=random").status_code == 422


# ---------------------------------------------------------- custom scoring


def test_game_with_custom_scoring(client):
    g = new_game(client, players=[{"name": "Bot", "strategy_version_id": vid(client, "Stop at 30")}],
                 scoring={"ace": 25, "three_nines": 0})
    assert g["scoring"] == {"ace": 25, "king": 5, "three_aces": 100, "three_kings": 50, "three_tens": -100, "three_nines": 0}
    for _ in range(100):
        ev = client.post(f"/api/games/{g['game_id']}/throw").json()["event"]["throw"]
        d = ev["dice"]
        if not (d[0] == d[1] == d[2]):
            assert ev["score"] == 25 * d.count(5) + 5 * d.count(4)
        if client.get(f"/api/games/{g['game_id']}").json()["awaiting"] == "finished":
            break


def test_simulation_with_custom_scoring_and_validation(client):
    sid = start_sim(client, scoring={"king": 8}, record_level="full")
    _wait_all(client)
    a = client.get(f"/api/simulations/{sid}/analysis").json()
    assert a["simulation"]["scoring"]["king"] == 8 and not a["simulation"]["scoring_is_default"]
    assert client.get(f"/api/simulations/{sid}").json()["config"]["scoring"]["king"] == 8
    for bad in ({"king": 8.5}, {"king": 99_999}, {"three_sevens": -300}):
        r = client.post("/api/simulations", json={"n_games": 5, "scoring": bad, "players": [
            {"name": "A", "strategy_version_id": vid(client, "Stop at 30")}]})
        assert r.status_code == 422, bad
