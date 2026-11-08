"""Turn and game rules, driven by scripted dice."""

import pytest

from ambiciosa.engine import (
    Decision,
    EndRule,
    Game,
    GameConfig,
    GameStatus,
    IllegalAction,
    PlayerConfig,
    ScriptedDice,
    TurnEndReason,
)

C, S = Decision.CONTINUE, Decision.STOP


def config(n=1, **kw):
    return GameConfig(players=tuple(PlayerConfig(f"P{i}") for i in range(n)), **kw)


def game(throws, n=1, order=None, **kw):
    return Game(config(n, **kw), seed=0, dice=ScriptedDice(throws), play_order=order or list(range(n)))


def play_turn(g, decisions):
    """Throw, then apply decisions after each positive throw until the turn ends."""
    seat = g.current_seat
    turns_before = g.players[seat].turns_taken
    decisions = list(decisions)
    g.throw()
    while g.awaiting == "decision":
        g.decide(decisions.pop(0))
        if g.awaiting == "throw" and g.current_seat == seat and g.current_turn is not None:
            g.throw()
    assert g.players[seat].turns_taken == turns_before + 1
    return g.history[-1]


# ------------------------------------------------------------------ turn rules


def test_spec_example_stop_banks_45():
    # +20 (AA), +15 (AK), +10 (A), then STOP
    g = game(["AA9", "AKJ", "A9T"])
    turn = play_turn(g, [C, C, S])
    assert [t.score for t in turn.throws] == [20, 15, 10]
    assert turn.turn_score == 45
    assert turn.end_reason is TurnEndReason.STOP
    assert g.players[0].score == 45


def test_spec_example_negative_after_accumulation_gives_minus_100():
    g = game(["AA9", "AKJ", "TTT"])
    turn = play_turn(g, [C, C])
    assert turn.turn_score == -100
    assert turn.end_reason is TurnEndReason.BUST_NEGATIVE
    assert g.players[0].score == -100


def test_zero_after_accumulation_gives_zero():
    g = game(["AAK", "JQT"])
    turn = play_turn(g, [C])
    assert turn.turn_score == 0
    assert turn.end_reason is TurnEndReason.BUST_ZERO
    assert g.players[0].score == 0


def test_first_throw_zero_ends_turn_without_decision():
    g = game(["JQ9"])
    g.throw()
    assert g.awaiting == "throw"  # next turn, no decision asked
    assert g.history[-1].turn_score == 0
    assert g.history[-1].throws[0].decision is None


def test_first_throw_three_sevens_scores_minus_300():
    g = game(["999"])
    play_turn(g, [])
    assert g.players[0].score == -300
    assert g.players[0].busts == 1


def test_decisions_and_running_totals_are_recorded():
    g = game(["AK9", "KKT", "JJQ"])
    turn = play_turn(g, [C, C])
    assert [(t.score, t.turn_points_after, t.decision) for t in turn.throws] == [
        (15, 15, C),
        (10, 25, C),
        (0, 0, None),
    ]


def test_scores_accumulate_across_turns_and_can_go_negative():
    g = game(["AAA", "999", "KKK", "TTT"])
    play_turn(g, [S])   # +100
    play_turn(g, [])    # -300
    play_turn(g, [S])   # +50
    play_turn(g, [])    # -100
    assert g.players[0].score == -250
    assert [t.banked_after for t in g.history] == [100, -200, -150, -250]
    assert g.players[0].turns_taken == 4
    assert g.players[0].total_throws == 4


def test_illegal_actions_are_rejected():
    g = game(["AA9", "AK9"])
    with pytest.raises(IllegalAction):
        g.decide(S)
    g.throw()
    with pytest.raises(IllegalAction):
        g.throw()
    g.decide("STOP")  # strings accepted


# --------------------------------------------------------------- winning rules


def test_reaching_exactly_the_target_mid_turn_wins_without_stop():
    g = game(["AA9", "AA9", "A9T"], target=50)
    g.throw()            # 20
    g.decide(C)
    g.throw()            # 40
    g.decide(C)
    rec = g.throw()      # 50 -> reaches target exactly
    assert rec.decision is None
    assert g.status is GameStatus.FINISHED
    assert g.winners == (0,)
    assert g.history[-1].end_reason is TurnEndReason.REACHED_TARGET
    assert g.players[0].score == 50


def test_exceeding_the_target_also_wins():
    g = game(["AAK", "AAA"], target=100)
    g.throw()
    g.decide(C)
    g.throw()
    assert g.is_over and g.players[0].score == 125


def test_win_counts_banked_score_plus_turn_total():
    g = game(["AAA", "AK9", "AAT"], target=120)
    play_turn(g, [S])     # 100 banked
    g.throw()             # 15 -> 115, below target
    assert g.awaiting == "decision"
    g.decide(C)
    g.throw()             # +20 -> 135 >= 120
    assert g.is_over and g.players[0].score == 135


def test_cannot_act_after_game_over():
    g = game(["AAA"], target=100)
    g.throw()
    assert g.awaiting == "finished"
    with pytest.raises(IllegalAction):
        g.throw()


def test_first_to_target_ends_immediately_in_multiplayer():
    # order: seat 1 then seat 0; seat 1 wins on the first throw
    g = game(["AAA"], n=2, order=[1, 0], target=100)
    g.throw()
    assert g.is_over
    assert g.winners == (1,)
    assert g.players[0].turns_taken == 0
    assert g.round_number == 1


def test_equal_turns_completes_the_round_and_higher_total_wins():
    g = game(["AAA", "AAK", "AAA"], n=2, order=[0, 1], target=100, end_rule=EndRule.EQUAL_TURNS)
    g.throw()                       # seat 0: 100, reaches target, turn auto-ends
    assert not g.is_over and g.current_seat == 1
    g.throw()                       # seat 1: 25
    g.decide(C)
    g.throw()                       # seat 1: +100 -> 125
    assert g.is_over
    assert g.winners == (1,)
    assert g.players[0].score == 100 and g.players[1].score == 125


def test_equal_turns_exact_tie_is_shared():
    g = game(["AAA", "AAA"], n=2, order=[0, 1], target=100, end_rule=EndRule.EQUAL_TURNS)
    g.throw()
    g.throw()
    assert g.status is GameStatus.FINISHED
    assert g.winners == (0, 1)
    assert g.winner is None


def test_equal_turns_player_who_cannot_catch_up_loses():
    g = game(["AAA", "999"], n=2, order=[0, 1], target=100, end_rule=EndRule.EQUAL_TURNS)
    g.throw()
    g.throw()
    assert g.winners == (0,)


def test_equal_turns_does_not_end_before_last_player_in_order():
    # 3 players, the middle one reaches the target; the third still plays.
    g = game(["JJJ", "AAA", "JQ9"], n=3, order=[2, 0, 1], target=100, end_rule="equal_turns")
    g.throw()          # seat 2: 0
    g.throw()          # seat 0: 100
    assert not g.is_over and g.current_seat == 1
    g.throw()          # seat 1: 0
    assert g.winners == (0,)


def test_max_turns_gives_unfinished_game_without_winner():
    g = game(["JJJ"] * 6, n=2, max_turns=3)
    for _ in range(6):
        g.throw()
    assert g.status is GameStatus.UNFINISHED
    assert g.winners == ()
    assert [p.turns_taken for p in g.players] == [3, 3]
    assert g.round_number == 3


def test_single_player_counts_turns_to_target():
    g = game(["AAA", "JJJ", "999", "AAA", "AAA", "AAA", "AAK", "AAA"], target=225)
    while not g.is_over:
        g.throw()
        if g.awaiting == "decision":
            g.decide(S)
    assert g.status is GameStatus.FINISHED
    assert g.players[0].turns_taken == 8
    assert g.players[0].score == 225
    assert g.history[-1].end_reason is TurnEndReason.REACHED_TARGET


# ----------------------------------------------------------- decision context


def test_decision_context_reflects_turn_and_game():
    g = game(["AAA", "AK9", "AAT"], n=2, order=[0, 1])
    g.throw()
    g.decide(S)          # seat 0: 100
    g.throw()            # seat 1: 15
    ctx = g.decision_context()
    assert ctx.turn_points == 15
    assert ctx.throws_this_turn == 1
    assert ctx.last_throw_score == 15
    assert ctx.my_score == 0
    assert ctx.best_opponent_score == 100
    assert ctx.gap_to_leader == -100
    assert ctx.points_to_target == 1000
    assert ctx.num_opponents == 1
    assert ctx.is_leading is False
    assert ctx.turn_number == 1


def test_decision_context_single_player():
    g = game(["AK9"])
    g.throw()
    ctx = g.decision_context()
    assert ctx.best_opponent_score is None
    assert ctx.num_opponents == 0
    assert ctx.is_leading is True
    assert ctx.gap_to_leader == 0


# ------------------------------------------------------------------ config


@pytest.mark.parametrize("n", [0, 7])
def test_player_count_limits(n):
    with pytest.raises(ValueError):
        config(n)


@pytest.mark.parametrize("kw", [{"target": 0}, {"max_turns": 0}])
def test_invalid_config_rejected(kw):
    with pytest.raises(ValueError):
        config(1, **kw)


def test_invalid_player_type_rejected():
    with pytest.raises(ValueError):
        PlayerConfig("X", player_type="robot")


def test_no_decision_context_after_game_over():
    g = game(["AAA"], target=100)
    g.throw()
    with pytest.raises(IllegalAction):
        g.decision_context()


def test_invalid_play_order_rejected():
    with pytest.raises(ValueError):
        Game(config(2), seed=1, play_order=[0, 0])
