"""Recording finished games as rows, at each recording level."""

import uuid

import numpy as np
import pytest

from ambiciosa.engine import Decision, EndRule, Face, Game, GameConfig, PlayerConfig, RandomDice, ScriptedDice
from ambiciosa.simulation import BatchRecorder, game_id_for
from ambiciosa.simulation.recorder import SCHEMAS, TABLES_FOR_LEVEL
from ambiciosa.strategies import PRESETS, play_automated

SIM = uuid.UUID("00000000-0000-4000-8000-000000000001")


def scripted_game(throws, decisions, config=None, play_order=(0, 1)):
    """Two automated seats; `decisions` answers every decision point in order."""
    config = config or GameConfig(
        players=(PlayerConfig("A", strategy=PRESETS[0]), PlayerConfig("B", strategy=PRESETS[1])), target=100
    )
    g = Game(config, seed=0, dice=ScriptedDice(throws), play_order=play_order)
    answers = iter(decisions)
    g.play_to_end(lambda seat, ctx: next(answers))
    return g


def test_game_ids_are_deterministic():
    assert game_id_for(SIM, 3) == game_id_for(SIM, 3) != game_id_for(SIM, 4)
    assert game_id_for(SIM, 3) != game_id_for(uuid.uuid4(), 3)


def test_unknown_level_rejected():
    with pytest.raises(ValueError):
        BatchRecorder(SIM, "everything")


def test_full_recording_of_a_scripted_game():
    # B (seat 1) plays first. B: AAA (+100) reaches the target at once and wins.
    # Order is [1, 0], so A never throws; n_rounds counts the first player in order (B).
    g = scripted_game(["AAA"], [], play_order=(1, 0))
    rec = BatchRecorder(SIM, "full")
    gid = rec.add(g, 7, duration_ms=1.5)
    assert gid == game_id_for(SIM, 7)
    assert list(rec.rows("game")) == [(str(gid), str(SIM), 7, "finished", 2, 1, 1.5)]  # B moved first: 1 round
    players = list(rec.rows("game_player"))
    #            seat play_order type        name strategy                                      score win   turns throws busts
    assert players[0][1:] == (0, 1, "automated", "A", str(PRESETS[0].strategy_version_id), 0, False, 0, 0, 0)
    assert players[1][1:] == (1, 0, "automated", "B", str(PRESETS[1].strategy_version_id), 100, True, 1, 1, 0)
    assert list(rec.rows("turn")) == [(str(gid), 1, 1, 1, "reached_target", 100, 100)]
    assert list(rec.rows("throw")) == [(str(gid), 1, 1, 1, 5, 5, 5, 100, 100, None, None)]


def test_turn_and_throw_rows_follow_the_history():
    # A: AK (15) continue, AA8 (+20=35) stop -> 35.  B: 777 (-300).  A: JJJ bust.  B: AAA... (target 100? no: -300+100)
    throws = ["AK9", "AAT", "999", "JJQ", "AAA", "AAA", "AAA", "AAA"]
    g = scripted_game(throws, [Decision.CONTINUE, Decision.STOP, Decision.CONTINUE, Decision.CONTINUE, Decision.CONTINUE])
    rec = BatchRecorder(SIM, "full")
    rec.add(g, 0)
    turns = [r[1:] for r in rec.rows("turn")]
    assert turns[:3] == [
        (0, 1, 2, "stop", 35, 35),
        (1, 1, 1, "bust_negative", -300, -300),
        (0, 2, 1, "bust_zero", 0, 35),
    ]
    throws_rows = [r[1:] for r in rec.rows("throw")]
    assert throws_rows[0] == (0, 1, 1, int(Face.ACE), int(Face.KING), int(Face.NINE), 15, 15, "CONTINUE", None)
    assert throws_rows[1][-4:] == (20, 35, "STOP", None)
    assert throws_rows[2][-4:] == (-300, -300, None, None)
    n_throws = sum(t.n_throws for t in g.history)
    assert len(throws_rows) == n_throws and len(turns) == len(g.history)


def test_levels_keep_only_their_tables():
    g = play_automated(GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), target=200), 3)
    for level, tables in TABLES_FOR_LEVEL.items():
        rec = BatchRecorder(SIM, level)
        rec.add(g, 0)
        arrow = rec.to_arrow()
        assert tuple(arrow) == tables
        for name, tbl in arrow.items():
            assert tbl.schema == SCHEMAS[name]


def test_summary_level_accepts_games_without_history():
    g = play_automated(GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), target=200), 3, record_history=False)
    rec = BatchRecorder(SIM, "summary")
    rec.add(g, 0)
    with pytest.raises(ValueError, match="record_history"):
        BatchRecorder(SIM, "turns").add(g, 0)


def test_reasons_are_kept_only_when_asked():
    g = play_automated(GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), target=200), 3)
    plain, kept = BatchRecorder(SIM, "full"), BatchRecorder(SIM, "full", keep_reasons=True)
    plain.add(g, 0)
    kept.add(g, 0)
    assert all(r[-1] is None for r in plain.rows("throw"))
    reasons = [r[-1] for r in kept.rows("throw") if r[-2] is not None]
    assert reasons and all("threshold" in r for r in reasons)


def test_unfinished_and_abandoned_status():
    cfg = GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]),), target=10**6, max_turns=3)
    g = play_automated(cfg, 1)
    rec = BatchRecorder(SIM, "summary")
    rec.add(g, 0)
    game_row = next(rec.rows("game"))
    assert game_row[3] == "unfinished" and game_row[5] == 3
    assert next(rec.rows("game_player"))[7] is False

    live = Game(cfg, seed=1)
    live.throw()
    rec = BatchRecorder(SIM, "summary")
    rec.add(live, 1)
    assert next(rec.rows("game"))[3] == "abandoned"


def test_shared_win_marks_every_winner():
    cfg = GameConfig(
        players=(PlayerConfig("A", strategy=PRESETS[0]), PlayerConfig("B", strategy=PRESETS[0])),
        target=100,
        end_rule=EndRule.EQUAL_TURNS,
    )
    g = scripted_game(["AAA", "AAA"], [], config=cfg)
    rec = BatchRecorder(SIM, "summary")
    rec.add(g, 0)
    assert [r[7] for r in rec.rows("game_player")] == [True, True]


def test_human_seat_has_no_strategy():
    cfg = GameConfig(players=(PlayerConfig("Ana", "human"), PlayerConfig("B", strategy=PRESETS[0])), target=100)
    g = Game(cfg, seed=0, dice=ScriptedDice(["AAA"]), play_order=(0, 1))
    g.throw()
    rec = BatchRecorder(SIM, "summary")
    rec.add(g, 0)
    ana = next(rec.rows("game_player"))
    assert ana[3:6] == ("human", "Ana", None)


def test_n_rounds_counts_turns_of_first_player():
    cfg = GameConfig(players=(PlayerConfig("A", strategy=PRESETS[0]), PlayerConfig("B", strategy=PRESETS[1])), target=300)
    g = play_automated(cfg, 12)
    rec = BatchRecorder(SIM, "summary")
    rec.add(g, 0)
    assert next(rec.rows("game"))[5] == g.players[g.play_order[0]].turns_taken


# ------------------------------------------------------------ buffered dice


@pytest.mark.parametrize("weights", [None, (1, 2, 3, 4, 5, 6), (0, 0, 1, 1, 0, 1)])
def test_buffered_dice_match_one_throw_at_a_time(weights):
    for seed in range(5):
        buffered = RandomDice(seed, weights)
        single = RandomDice(np.random.default_rng(seed), weights)  # a passed-in generator is never buffered
        assert [buffered.roll() for _ in range(1000)] == [single.roll() for _ in range(1000)]


def test_shared_generator_is_not_overdrawn():
    rng = np.random.default_rng(5)
    dice = RandomDice(rng)
    dice.roll()
    reference = np.random.default_rng(5)
    reference.integers(0, 6, size=3)
    assert rng.random() == reference.random()
