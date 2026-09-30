import pytest

from hots_draft.draft import DraftState
from hots_draft.recommendations import rank_heroes


def hero(
    name, *, role="Ranged Assassin", synergies=(), counters=(), strong=(), weak=()
):
    return {
        "name": name,
        "role": role,
        "synergies": {"heroes": [{"id": id_} for id_ in synergies]},
        "counters": {"heroes": [{"id": id_} for id_ in counters]},
        "maps": {
            "stronger": [{"id": id_} for id_ in strong],
            "weaker": [{"id": id_} for id_ in weak],
        },
    }


def test_no_context_does_not_invent_recommendations():
    assert rank_heroes({"a": hero("A")}, DraftState()) == []


def test_pick_counter_direction_and_threat_penalty():
    heroes = {
        "enemy": hero("Enemy", counters=("answer",)),
        "answer": hero("Answer"),
        "risky": hero("Risky", counters=("enemy",), strong=("map",)),
    }
    draft = DraftState(map_id="map")
    draft.assign("enemies", 0, "enemy")
    results = rank_heroes(heroes, draft)
    assert [result.hero_id for result in results] == ["answer"]
    assert results[0].reasons == ["Counters Enemy"]


def test_ban_protects_ally_and_denies_enemy_synergy():
    heroes = {
        "ally": hero("Ally", counters=("threat",)),
        "enemy": hero("Enemy", synergies=("partner",)),
        "threat": hero("Threat"),
        "partner": hero("Partner"),
    }
    draft = DraftState()
    draft.assign("allies", 0, "ally")
    draft.assign("enemies", 0, "enemy")
    results = rank_heroes(heroes, draft, mode="ban")
    assert results[0].hero_id == "threat"
    assert "Protects Ally" in results[0].reasons[0]
    assert results[1].reasons == ["Denies synergy with Enemy"]
    draft.assign("ally_bans", 0, "threat")
    assert [result.hero_id for result in rank_heroes(heroes, draft, mode="ban")] == [
        "partner"
    ]


def test_team_role_coverage_and_side_switch():
    heroes = {"damage": hero("Damage"), "healer": hero("Healer", role="Healer")}
    draft = DraftState()
    draft.assign("enemies", 0, "damage")
    results = rank_heroes(heroes, draft, side="enemies")
    assert results[0].hero_id == "healer"
    assert "missing healer" in results[0].reasons[0]
    assert rank_heroes(heroes, draft, side="allies") == []


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        rank_heroes({}, DraftState(), mode="guess")


def test_full_ranking_includes_neutral_and_negative_matches():
    heroes = {
        "best": hero("Best", strong=("map",)),
        "neutral": hero("Neutral"),
        "weak": hero("Weak", weak=("map",)),
        "banned": hero("Banned"),
    }
    draft = DraftState(map_id="map")
    draft.assign("ally_bans", 0, "banned")
    results = rank_heroes(heroes, draft, include_all=True)
    assert [r.hero_id for r in results] == ["best", "neutral", "weak"]
    assert [r.score for r in results] == [3, 0, -3]
    assert results[-1].warnings


def test_picked_rankings_use_own_team_without_self_synergy():
    from hots_draft.recommendations import rank_picked_heroes

    heroes = {
        "ally": hero("Ally", synergies=("partner",)),
        "partner": hero("Partner"),
        "enemy": hero("Enemy", counters=("ally",)),
    }
    draft = DraftState()
    draft.assign("allies", 0, "ally")
    draft.assign("allies", 1, "partner")
    draft.assign("enemies", 0, "enemy")
    results = rank_picked_heroes(heroes, draft)
    assert [r.hero_id for r in results] == ["ally", "partner", "enemy"]
    assert [r.score for r in results] == [9, 4, -6]
    assert draft.slots["allies"][:2] == ["ally", "partner"]
