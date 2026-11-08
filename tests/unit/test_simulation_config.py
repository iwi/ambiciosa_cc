"""Seeds, simulation configs and chunking."""

import numpy as np
import pytest
from pydantic import ValidationError

from ambiciosa.engine import EndRule
from ambiciosa.simulation import (
    FULL_RECORD_LIMIT,
    SimulationConfig,
    chunk_bounds,
    find_preset,
    game_seed,
    new_master_seed,
)
from ambiciosa.strategies import PRESETS, StrategySpec

# ------------------------------------------------------------------ seeds


def test_game_seed_is_the_spawned_child():
    children = np.random.SeedSequence(99).spawn(5)
    for i, child in enumerate(children):
        assert game_seed(99, i).generate_state(4).tolist() == child.generate_state(4).tolist()


def test_game_seeds_differ_by_index_and_master():
    states = {tuple(game_seed(m, i).generate_state(2)) for m in (1, 2) for i in range(50)}
    assert len(states) == 100


@pytest.mark.parametrize("master, index", [(-1, 0), (2**64, 0), (0, -1)])
def test_game_seed_rejects_out_of_range(master, index):
    with pytest.raises(ValueError):
        game_seed(master, index)


def test_largest_master_seed_is_accepted():
    game_seed(2**64 - 1, 10**9)


def test_new_master_seed_fits_ubigint():
    seeds = {new_master_seed() for _ in range(20)}
    assert len(seeds) > 1 and all(0 <= s < 2**64 for s in seeds)


# ----------------------------------------------------------------- config


def cfg(**kw):
    data = {"n_games": 10, "players": ["Stop at 30", "Stop at 50"], **kw}
    return SimulationConfig.model_validate(data)


def test_record_level_defaults_follow_decision_7():
    assert cfg(n_games=FULL_RECORD_LIMIT).record_level == "full"
    assert cfg(n_games=FULL_RECORD_LIMIT + 1).record_level == "summary"
    assert cfg(n_games=10**6, record_level="turns").record_level == "turns"


def test_missing_seed_is_chosen_and_kept():
    c = cfg()
    assert 0 <= c.master_seed < 2**64
    assert c.model_copy().master_seed == c.master_seed


def test_default_name_lists_strategies():
    assert cfg().name == "Stop at 30 vs Stop at 50"
    assert cfg(name="Mine").name == "Mine"


def test_preset_lookup_is_case_insensitive():
    assert find_preset("  stop AT 30 ") is PRESETS[0]
    with pytest.raises(ValueError, match="unknown preset"):
        find_preset("Stop at 31")


def test_seat_forms():
    c = SimulationConfig.model_validate({
        "n_games": 1,
        "players": [
            "Three throws",
            {"name": "Me", "strategy": "Stop at 50"},
            {"name": "Inline", "strategy": {"type": "threshold", "params": {"threshold": 40}}},
            {"strategy": {"name": "Named", "type": "max_throws", "params": {"max_throws": 2}}},
            PRESETS[0],
        ],
    })
    names = [s.name for s in c.players]
    assert names == ["Three throws", "Me", "Inline", "Named", "Stop at 30"]
    assert c.players[2].strategy.name == "threshold (threshold=40)"
    assert c.players[2].strategy.params == {"threshold": 40}


def test_invalid_configs_are_rejected():
    with pytest.raises(ValidationError):
        cfg(n_games=0)
    with pytest.raises(ValidationError):
        cfg(players=[])
    with pytest.raises(ValidationError):
        cfg(players=["Stop at 30"] * 7)
    with pytest.raises(ValidationError):
        cfg(players=[{"name": "X", "strategy": {"type": "threshold", "params": {"threshold": -5}}}])
    with pytest.raises(ValidationError):
        cfg(unknown_key=1)
    with pytest.raises(ValidationError):
        cfg(record_level="everything")
    with pytest.raises(ValidationError):
        cfg(face_weights=[1, 1, 1])


def test_face_weights_are_normalised():
    assert cfg(face_weights=[2, 2, 2, 2, 2, 2]).face_weights == pytest.approx((1 / 6,) * 6)


def test_game_config_carries_rules_and_strategies():
    c = cfg(target=500, end_rule="equal_turns", max_turns=50, face_weights=[1, 1, 1, 1, 1, 3])
    g = c.game_config()
    assert (g.target, g.end_rule, g.max_turns) == (500, EndRule.EQUAL_TURNS, 50)
    assert g.face_weights[5] == pytest.approx(3 / 8)
    assert [p.strategy for p in g.players] == [PRESETS[0], PRESETS[1]]


def test_strategies_are_distinct_versions():
    c = cfg(players=["Stop at 30", "Stop at 30", "Stop at 50"])
    assert c.strategies() == [PRESETS[0], PRESETS[1]]


def test_stored_form_round_trips():
    c = cfg(players=["Stop at 30", {"name": "B", "strategy": {"type": "random", "params": {"p_continue": 0.5}}}])
    stored = c.stored_dict()
    assert stored["players"][0] == {"name": "Stop at 30", "player_type": "automated",
                                   "strategy_version_id": str(PRESETS[0].strategy_version_id)}
    assert "params" not in str(stored["players"])          # parameters live in the strategy table only
    specs = {str(s.strategy_version_id): s for s in c.strategies()}
    assert SimulationConfig.from_stored(stored, specs) == c


def test_with_strategies_replaces_each_seat():
    c = cfg()
    other = StrategySpec.create("Other", "threshold", {"threshold": 10})
    c2 = c.with_strategies([other, other])
    assert [s.strategy for s in c2.players] == [other, other]
    assert [s.name for s in c2.players] == [s.name for s in c.players]
    with pytest.raises(ValueError):
        c.with_strategies([other])


def test_yaml_loading_with_overrides(tmp_path):
    path = tmp_path / "run.yaml"
    path.write_text(
        "name: From YAML\nn_games: 5000\nmaster_seed: 7\nend_rule: equal_turns\n"
        "players:\n  - Stop at 30\n  - name: Bold\n    strategy: {type: threshold, params: {threshold: 60}}\n"
    )
    c = SimulationConfig.from_yaml(path)
    assert (c.name, c.n_games, c.master_seed, c.end_rule) == ("From YAML", 5000, 7, EndRule.EQUAL_TURNS)
    assert c.players[1].strategy.params == {"threshold": 60}
    c = SimulationConfig.from_yaml(path, n_games=20_000, master_seed=None, workers=3)
    assert (c.n_games, c.master_seed, c.workers, c.record_level) == (20_000, 7, 3, "summary")


def test_yaml_must_be_a_mapping(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        SimulationConfig.from_yaml(path)


# ---------------------------------------------------------------- chunking


@pytest.mark.parametrize("n, size, workers", [(1, 1000, 8), (10, 3, 1), (10_000, 1000, 2), (12_345, 500, 3), (7, 1000, 4)])
def test_chunks_cover_every_game_once(n, size, workers):
    chunks = chunk_bounds(n, size, workers)
    covered = [i for a, b in chunks for i in range(a, b)]
    assert covered == list(range(n))
    assert all(0 < b - a <= size for a, b in chunks)


def test_small_runs_are_split_between_workers():
    assert len(chunk_bounds(100, 1000, 2)) == 8
    assert len(chunk_bounds(1_000_000, 1000, 2)) == 1000
