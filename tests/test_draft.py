import pytest

from hots_draft.draft import DraftState


def test_duplicate_picks_and_bans_are_rejected():
    draft = DraftState()
    draft.assign("allies", 0, "jaina")
    with pytest.raises(ValueError, match="already picked"):
        draft.assign("enemy_bans", 0, "jaina")
    draft.assign("allies", 0, None)
    draft.assign("enemy_bans", 0, "jaina")
    assert draft.unavailable == {"jaina"}


def test_roundtrip_and_stale_hero_rejection():
    draft = DraftState(map_id="cursed-hollow", first_pick=False)
    draft.commit("jaina")
    assert DraftState.from_dict(draft.to_dict(), {"jaina"}, {"cursed-hollow"}) == draft
    with pytest.raises(ValueError, match="Unknown hero"):
        DraftState.from_dict(draft.to_dict(), set(), {"cursed-hollow"})


def test_instances_do_not_share_slots():
    first, second = DraftState(), DraftState()
    first.assign("allies", 0, "jaina")
    assert not second.unavailable


@pytest.mark.parametrize("first", [True, False])
def test_entire_pipeline_and_team_flip(first):
    draft = DraftState(map_id="map", first_pick=first)
    first_side = "allies" if first else "enemies"
    second_side = "enemies" if first else "allies"
    expected = [
        (first_side, "ban"),
        (second_side, "ban"),
        (first_side, "ban"),
        (second_side, "ban"),
        (first_side, "pick"),
        (second_side, "pick"),
        (second_side, "pick"),
        (first_side, "pick"),
        (first_side, "pick"),
        (second_side, "ban"),
        (first_side, "ban"),
        (second_side, "pick"),
        (second_side, "pick"),
        (first_side, "pick"),
        (first_side, "pick"),
        (second_side, "pick"),
    ]
    for index, (side, mode) in enumerate(expected):
        assert (draft.current_action.side, draft.current_action.mode) == (side, mode)
        draft.commit(f"hero-{index}")
    assert draft.completed and draft.current_action is None
    assert len(draft.unavailable) == 16
    assert all(
        len([id_ for id_ in draft.slots[side] if id_]) == 5
        for side in ("allies", "enemies")
    )
    with pytest.raises(ValueError, match="complete"):
        draft.commit("extra")
    draft.undo()
    assert not draft.completed and draft.current_action.side == second_side
    assert "hero-15" not in draft.unavailable


def test_skipped_bans_resume_and_picks_cannot_be_skipped():
    draft = DraftState(map_id="map", first_pick=True)
    for _ in range(4):
        draft.commit(None)
    restored = DraftState.from_dict(draft.to_dict(), set(), {"map"})
    assert restored.current_action.mode == "pick"
    with pytest.raises(ValueError, match="Only bans"):
        restored.commit(None)
    restored.undo()
    assert restored.current_action.group == "enemy_bans"


def test_session_rejects_out_of_order_slots():
    draft = DraftState(map_id="map", first_pick=True)
    draft.commit("a")
    value = draft.to_dict()
    value["slots"]["enemies"][4] = "b"
    with pytest.raises(ValueError, match="history"):
        DraftState.from_dict(value, {"a", "b"}, {"map"})
