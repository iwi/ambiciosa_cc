"""Golden games: a fingerprint of 200 complete games that must never change by accident.

The games cover six-player, equal-turns, shared-win, single-player, loaded-dice
and changed-score configurations, with every strategy type. The fingerprint
covers playing order, winners, status, scores, every throw's dice, score,
decision and reason. It was taken from version 0.6.1 and confirmed unchanged
by the Phase 7 optimisations; if a deliberate rule change alters it, update
the constant and say so in the architecture document.
"""

import hashlib

from ambiciosa.engine import EndRule, GameConfig, PlayerConfig, Scoring
from ambiciosa.strategies import PRESETS, StrategySpec, play_automated

GOLDEN = "2991f4b547b203316fb9"


def _configs():
    extra = [StrategySpec.create("And", "combined", {"threshold": 40, "max_throws": 2, "logic": "and"}),
             StrategySpec.create("Close", "game_state", {"leading_threshold": 20, "trailing_threshold": 70,
                                                         "close_to_win_points": 150, "close_threshold": 40})]
    s = list(PRESETS) + extra
    return [
        GameConfig(players=tuple(PlayerConfig(x.name, strategy=x) for x in s[:6])),
        GameConfig(players=tuple(PlayerConfig(x.name, strategy=x) for x in (s[6], s[7], s[4])),
                   end_rule=EndRule.EQUAL_TURNS, target=400),
        GameConfig(players=(PlayerConfig("solo", strategy=s[5]),), max_turns=60, face_weights=(1, 2, 1, 1, 1, 2),
                   scoring=Scoring(ace=12, three_tens=30)),
        GameConfig(players=(PlayerConfig("a", strategy=s[0]), PlayerConfig("b", strategy=s[0])), target=60,
                   end_rule=EndRule.EQUAL_TURNS),
    ]


def test_golden_games_are_unchanged():
    h = hashlib.sha256()
    for cfg in _configs():
        for seed in range(50):
            g = play_automated(cfg, seed)
            h.update(repr((g.play_order, g.winners, g.status, g.scores(), g.round_number,
                           [(p.turns_taken, p.total_throws, p.busts) for p in g.players],
                           [(t.seat, t.turn_number, t.end_reason, t.turn_score, t.banked_after,
                             [(r.dice, r.score, r.turn_points_after, r.decision, r.reason) for r in t.throws])
                            for t in g.history])).encode())
    assert h.hexdigest()[:20] == GOLDEN
