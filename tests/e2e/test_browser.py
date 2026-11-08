"""The web app in a real browser (Phase 5 completion criterion).

A live server runs on a free port with a fresh database; Playwright's
Chromium drives the built React app. Skipped when the app is not built
(web/ → npm run build) or Chromium is not available.
"""

import re
import socket
import threading
import time

import pytest

from ambiciosa.api import create_app
from ambiciosa.api.main import default_static_dir

pytestmark = pytest.mark.e2e

playwright_api = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if default_static_dir() is None:
        pytest.skip("web app not built")
    import uvicorn

    app = create_app(tmp_path_factory.mktemp("e2e") / "e2e.duckdb")
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)
    app.state.db.close()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.base = server
    yield pg
    ctx.close()
    assert errors == [], f"browser errors: {errors}"


def test_full_human_vs_bot_game(page):
    page.goto(page.base + "/play")
    page.get_by_role("button", name="Start game").wait_for()
    page.get_by_label("Target").fill("150")                     # a short game
    page.get_by_role("button", name="Start game").click()

    throw = page.get_by_role("button", name="Throw", exact=True)
    bank = page.get_by_role("button", name=re.compile(r"^Bank \d+"))
    again = page.get_by_role("button", name="Throw again")
    play_again = page.get_by_role("button", name="Play again")
    speed = page.get_by_label("Speed")

    human_throws = bot_seen = 0
    deadline = time.monotonic() + 180
    while not play_again.is_visible():
        assert time.monotonic() < deadline, "game did not finish in time"
        if throw.is_visible() and throw.is_enabled():
            throw.click()
            human_throws += 1
        elif bank.is_visible() and bank.is_enabled():
            points = int(bank.inner_text().split()[1].replace(",", ""))
            (bank if points >= 20 else again).click()
            human_throws += points < 20
        elif speed.is_visible():
            bot_seen += 1
            try:  # the menu disappears when the bot's turn ends, so never wait long for it
                if speed.input_value(timeout=500) != "fast":
                    speed.select_option("fast", timeout=500)
            except playwright_api.Error:
                pass
        page.wait_for_timeout(60)

    outcome = page.locator(".outcome").inner_text()
    assert re.search(r"wins with|share the win", outcome)
    assert human_throws > 0 and bot_seen > 0
    assert page.locator(".log-reason").count() > 0              # the bot explained its decisions

    page.get_by_role("link", name="See it in Analyse").click()
    page.locator(".results .metrics table tbody tr").first.wait_for()
    assert page.locator("table.runs").get_by_text("played").count() == 1
    assert page.locator(".results .metrics table tbody tr").count() == 2
    # The played game's record keeps the bot's reasons.
    page.locator(".results").get_by_role("tab", name="Games").click()
    page.locator(".record-turns .log-reason").first.wait_for()
    assert "threshold" in page.locator(".record-turns").inner_text()


def test_run_a_simulation(page):
    page.goto(page.base + "/simulate")
    page.get_by_role("button", name="Start simulation").wait_for()
    page.get_by_label("Games", exact=True).fill("400")
    page.get_by_label("Name", exact=True).fill("Browser run")
    page.get_by_label("Seed", exact=True).fill("42")
    page.get_by_label("Processes", exact=True).fill("1")
    page.get_by_label("Target").fill("300")
    page.get_by_role("button", name="Start simulation").click()

    page.get_by_role("progressbar").wait_for()
    page.get_by_role("link", name="Open in Analyse").wait_for(timeout=120_000)
    assert "400 of 400 games" in page.locator(".progress-figures").inner_text()
    rows = page.locator(".run table.data tbody tr")
    assert rows.count() == 2
    rates = [float(r.locator("td").first.inner_text().rstrip("%")) for r in rows.all()]
    assert sum(rates) == pytest.approx(100, abs=0.2)
    assert page.get_by_role("link", name="Download Parquet").get_attribute("href").endswith("format=parquet")

    page.get_by_role("link", name="Open in Analyse").click()
    page.locator(".results").get_by_role("heading", name="Browser run").wait_for()
    assert "42" in page.locator(".config-grid").inner_text()


def test_create_and_version_a_strategy_from_its_generated_form(page):
    page.goto(page.base + "/strategies")
    page.get_by_role("button", name="New strategy").click()
    page.get_by_label("Name", exact=True).fill("Forty or three")
    page.get_by_label("Type").select_option(label="Combined conditions")
    # These inputs come from the strategy type's JSON Schema.
    page.get_by_label("Points to bank").fill("0")
    page.get_by_role("button", name="Add strategy").click()
    assert page.get_by_text("Must be at least 1.").is_visible()
    page.get_by_label("Points to bank").fill("40")
    page.get_by_label("Throws to bank").fill("3")
    page.get_by_label("Combine conditions with").select_option("and")
    page.get_by_role("button", name="Add strategy").click()
    page.get_by_text("Forty or three added.").wait_for()

    item = page.locator(".library li", has_text="Forty or three")
    assert "Points to bank 40, Throws to bank 3, Combine conditions with and" in item.inner_text()

    page.get_by_label("Points to bank").fill("45")
    page.get_by_role("button", name="Save new version").click()
    page.get_by_text("Saved as version 2.").wait_for()
    assert "version 2" in page.locator(".library li", has_text="Forty or three").inner_text()
    assert page.locator(".versions li").count() == 2

    # The new strategy is offered to bots in Play.
    page.goto(page.base + "/play")
    page.get_by_label("Player 2 strategy").wait_for()
    options = page.get_by_label("Player 2 strategy").locator("option").all_inner_texts()
    assert "Forty or three (v2)" in options


def _start_run(page, **body):
    """Start a simulation through the API and wait until it has finished."""
    lib = page.request.get(page.base + "/api/strategies").json()
    ids = {s["name"]: s["strategy_version_id"] for s in lib}
    players = [{"name": n, "strategy_version_id": ids[n]} for n in body.pop("players")]
    sid = page.request.post(page.base + "/api/simulations",
                            data={"workers": 1, "players": players, **body}).json()["simulation_id"]
    for _ in range(600):
        if page.request.get(f"{page.base}/api/simulations/{sid}").json()["status"] == "completed":
            return sid
        page.wait_for_timeout(100)
    raise AssertionError("run did not finish")


def test_analyse_a_run_and_compare_runs(page):
    multi = _start_run(page, name="E2E three-way", n_games=300, master_seed=3, target=300, record_level="full",
                       players=["Stop at 30", "Stop at 50", "Coin flip 75%"])
    solo = _start_run(page, name="E2E solo", n_games=300, master_seed=4, target=300, record_level="summary",
                      players=["Stop at 30"])
    expected = page.request.get(f"{page.base}/api/simulations/{multi}/analysis").json()

    page.goto(f"{page.base}/analyse")
    page.get_by_role("button", name="E2E three-way").click()
    results = page.locator(".results")
    results.get_by_role("heading", name="E2E three-way").wait_for()

    # Summary: configuration, the spec 3.3 metrics, charts drawn
    assert "Bank at 50" in results.locator(".seats-table").inner_text()
    rows = results.locator(".metrics table tbody tr")
    rows.first.wait_for()
    assert rows.count() == 3
    first = expected["players"][0]
    row_text = rows.first.inner_text()
    assert f"{first['win_rate'] * 100:.1f}%" in row_text
    assert f"{first['turns_to_target_mean']:.1f}" in row_text
    assert str(first["turns_to_target_min"]) in row_text and str(first["turns_to_target_max"]) in row_text
    results.locator(".chart-plot .main-svg").first.wait_for(timeout=30_000)
    assert results.locator(".chart").count() == 3

    # The table view of a chart carries the same numbers
    win_chart = results.locator(".chart", has_text="Win rate").first
    win_chart.get_by_role("button", name="Table").click()
    assert f"{first['win_rate'] * 100:.1f}%" in win_chart.locator("table").inner_text()

    for tab, marker in [("Distributions", "Final scores"), ("Turns", "How turns end"), ("Throws", "Throw scores")]:
        results.get_by_role("tab", name=tab).click()
        results.get_by_text(marker, exact=True).wait_for()
        results.locator(".chart-plot .main-svg").first.wait_for(timeout=30_000)
    assert "consistent with the face weights" in results.locator(".checks").inner_text() or \
        "differ" in results.locator(".checks").inner_text()

    # Games: the list, and the record of a chosen game with its throws
    results.get_by_role("tab", name="Games").click()
    results.locator(".games-table tbody tr").first.wait_for()
    results.locator(".games-table tbody tr").nth(2).get_by_role("button").click()
    results.get_by_role("heading", name="Game 3").wait_for()
    assert results.locator(".record-turns .dice-row").count() > 0
    results.get_by_label("Won by").select_option(label="Stop at 50")
    page.wait_for_timeout(300)
    for winner in results.locator(".games-table tbody tr td:nth-child(2)").all_inner_texts():
        assert "Stop at 50" in winner

    # A summary-level single-player run: no win columns, turn and throw tabs explain what is missing
    page.get_by_role("button", name="E2E solo").click()
    results.get_by_role("heading", name="E2E solo").wait_for()
    headers = results.locator(".metrics thead").inner_text()
    assert "Win rate" not in headers and "Median" in headers and "SD" in headers
    results.get_by_role("tab", name="Throws").click()
    assert results.get_by_text("were not kept for this run").is_visible()

    # Compare: tick both
    page.get_by_label("Select E2E three-way").click()
    page.get_by_role("heading", name="Comparing 2 runs").wait_for()
    matrix = page.locator(".matrix")
    assert "Stop at 30" in matrix.inner_text() and "not in this run" in matrix.inner_text()
    page.locator(".compare-view .chart-plot .main-svg").first.wait_for(timeout=30_000)
    assert sorted(page.url.split("run=")[1:]) == sorted([f"{solo}&", multi]) or set(
        p.split("&")[0] for p in page.url.split("run=")[1:]) == {solo, multi}


def test_changed_scores_reach_the_game_the_run_and_analyse(page):
    # Play: change the scores; the guide beside the form and in the game shows them.
    page.goto(page.base + "/play")
    page.get_by_role("button", name="Start game").wait_for()
    page.get_by_label("Change the scores").check()
    page.get_by_label("Each Ace").fill("25")
    page.get_by_label("Three 9s").fill("-500")
    guide = page.locator(".scoring")
    assert "+25 per A" in guide.inner_text() and "−500, the turn scores −500" in guide.inner_text()
    page.get_by_label("Each King").fill("2.5")
    page.get_by_role("button", name="Start game").click()          # blocked: not a whole number
    assert page.get_by_role("button", name="Start game").is_visible()
    assert page.get_by_text("Enter a whole number.").is_visible()
    page.get_by_label("Each King").fill("5")
    page.get_by_role("button", name="Start game").click()
    page.get_by_role("heading", name="Scoring in this game").wait_for()
    assert "+25 per A" in page.locator(".play-main .scoring").inner_text()
    # The dice show 9 and 10 in the guide.
    assert "10" in page.locator(".play-main .scoring").inner_text() and "9" in page.locator(".play-main .scoring").inner_text()

    # Simulate with the same change; Analyse reports it and the exact probabilities follow it.
    page.goto(page.base + "/simulate")
    page.get_by_role("button", name="Start simulation").wait_for()
    page.get_by_label("Games", exact=True).fill("150")
    page.get_by_label("Name", exact=True).fill("Aces worth 25")
    page.get_by_label("Processes", exact=True).fill("1")
    page.get_by_label("Detail kept").select_option("full")
    page.get_by_label("Target").fill("300")
    page.get_by_label("Change the scores").check()
    page.get_by_label("Each Ace").fill("25")
    page.get_by_role("button", name="Start simulation").click()
    page.get_by_role("link", name="Open in Analyse").wait_for(timeout=120_000)
    page.get_by_role("link", name="Open in Analyse").click()
    results = page.locator(".results")
    results.get_by_role("heading", name="Aces worth 25").wait_for()
    assert "Each Ace +25" in results.locator(".config-grid").inner_text()
    results.get_by_role("tab", name="Throws").click()
    faces = results.locator(".chart", has_text="Faces")
    faces.get_by_role("button", name="Table").click()
    assert faces.locator("tbody th").all_inner_texts() == ["9", "10", "J", "Q", "K", "A"]
    scores = results.locator(".chart", has_text="Throw scores")
    scores.get_by_role("button", name="Table").click()
    assert "25" in scores.locator("tbody th").all_inner_texts()      # one Ace now scores 25
