"""Complete games between strategies."""

import pytest

from ambiciosa.engine import Decision, Game, GameConfig, GameStatus, PlayerConfig, ScriptedDice
from ambiciosa.strategies import PRESETS, AutomatedPlayers, StrategySpec, play_automated


def bot(name, type, params=None):
    return PlayerConfig(name, strategy=StrategySpec.create(name, type, params or {}))


def all_presets():
    return GameConfig(players=tuple(PlayerConfig(p.name, strategy=p) for p in PRESETS))


def fingerprint(g):
    return (g.play_order, g.winners, g.scores(), [[(t.dice, t.decision, t.reason) for t in turn.throws] for turn in g.history])


def test_same_seed_reproduces_game_with_random_strategy():
    assert fingerprint(play_automated(all_presets(), 11)) == fingerprint(play_automated(all_presets(), 11))


def test_random_strategy_does_not_change_the_dice():
    # Same seed, different random strategies: play order and the first throw must be identical.
    a = play_automated(GameConfig(players=(bot("A", "random", {"p_continue": 0.1}), bot("B", "threshold"))), 5)
    b = play_automated(GameConfig(players=(bot("A", "random", {"p_continue": 0.9}), bot("B", "threshold"))), 5)
    assert a.play_order == b.play_order
    assert a.history[0].throws[0].dice == b.history[0].throws[0].dice


def test_decisions_and_reasons_are_recorded():
    g = Game(
        GameConfig(players=(bot("T", "threshold", {"threshold": 30}),)),
        seed=0,
        dice=ScriptedDice(["AK9", "AAT", "AAK", "JJJ"]),
    )
    players = AutomatedPlayers(g)
    g.throw()                                     # 15
    r = players(0, g.decision_context())
    g.decide(r.decision, r.reason)
    g.throw()                                     # +20 = 35 -> stop
    r = players(0, g.decision_context())
    g.decide(r.decision, r.reason)
    turn = g.history[0]
    assert [t.decision for t in turn.throws] == [Decision.CONTINUE, Decision.STOP]
    assert turn.throws[1].reason == "turn total 35 reached threshold 30"
    assert turn.turn_score == 35


def test_human_seat_is_not_decided_automatically():
    g = Game(GameConfig(players=(PlayerConfig("Ana", "human"), bot("B", "threshold"))), seed=1)
    players = AutomatedPlayers(g)
    assert not players.is_automated(0) and players.is_automated(1)
    with pytest.raises(ValueError, match="human"):
        players(0, g.decision_context())


def test_automated_player_without_strategy_rejected():
    g = Game(GameConfig(players=(PlayerConfig("Nobody"),)), seed=1)
    with pytest.raises(ValueError, match="StrategySpec"):
        AutomatedPlayers(g)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.name)
def test_every_preset_finishes_single_player_games(preset):
    for seed in range(20):
        g = play_automated(GameConfig(players=(PlayerConfig("Solo", strategy=preset),)), seed, record_history=False)
        assert g.status is GameStatus.FINISHED


def test_game_state_strategy_switches_between_situations():
    # Against a steady opponent the strategy should bank both while leading and while trailing.
    gs = StrategySpec.create("GS", "game_state", {"leading_threshold": 20, "trailing_threshold": 80, "close_to_win_points": None})
    strong = StrategySpec.create("Strong", "threshold", {"threshold": 30})
    situations = []
    for seed in range(40):
        g = play_automated(GameConfig(players=(PlayerConfig("GS", strategy=gs), PlayerConfig("S", strategy=strong))), seed)
        for t in g.history:
            if t.seat == 0 and t.end_reason.value == "stop":
                situations.append(t.throws[-1].reason.split(":")[0].split(" ")[0])
    assert {"leading", "trailing"} <= set(situations)
