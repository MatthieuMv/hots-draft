"""Draft state independent of the desktop UI and future recommendation engine."""

from dataclasses import asdict, dataclass, field

# F = first-pick team, S = second-pick team. Double-pick rounds are split
# into individual actions; the mid-ban round starts with the second-pick team.
ORDER = (
    ("F", "ban"),
    ("S", "ban"),
    ("F", "ban"),
    ("S", "ban"),
    ("F", "pick"),
    ("S", "pick"),
    ("S", "pick"),
    ("F", "pick"),
    ("F", "pick"),
    ("S", "ban"),
    ("F", "ban"),
    ("S", "pick"),
    ("S", "pick"),
    ("F", "pick"),
    ("F", "pick"),
    ("S", "pick"),
)


@dataclass(frozen=True)
class DraftAction:
    group: str
    index: int
    mode: str

    @property
    def side(self) -> str:
        return "allies" if self.group in ("allies", "ally_bans") else "enemies"


@dataclass
class DraftState:
    map_id: str | None = None
    first_pick: bool | None = None
    history: list[str | None] = field(default_factory=list)
    slots: dict[str, list[str | None]] = field(
        default_factory=lambda: {
            "allies": [None] * 5,
            "enemies": [None] * 5,
            "ally_bans": [None] * 3,
            "enemy_bans": [None] * 3,
        }
    )

    @property
    def unavailable(self) -> set[str]:
        return {hero for slots in self.slots.values() for hero in slots if hero}

    def assign(self, group: str, index: int, hero_id: str | None) -> None:
        if group not in self.slots or not 0 <= index < len(self.slots[group]):
            raise ValueError("Unknown draft slot")
        if (
            hero_id
            and hero_id in self.unavailable
            and self.slots[group][index] != hero_id
        ):
            raise ValueError("This hero is already picked or banned")
        self.slots[group][index] = hero_id

    def to_dict(self) -> dict:
        return {"version": 2, **asdict(self)}

    @property
    def actions(self) -> list[DraftAction]:
        if self.first_pick is None:
            return []
        counts = {group: 0 for group in self.slots}
        actions = []
        for team, mode in ORDER:
            allied = (team == "F") == self.first_pick
            group = (
                ("allies" if allied else "enemies")
                if mode == "pick"
                else ("ally_bans" if allied else "enemy_bans")
            )
            actions.append(DraftAction(group, counts[group], mode))
            counts[group] += 1
        return actions

    @property
    def current_action(self) -> DraftAction | None:
        return (
            self.actions[len(self.history)]
            if self.configured and len(self.history) < len(ORDER)
            else None
        )

    @property
    def configured(self) -> bool:
        return bool(self.map_id) and isinstance(self.first_pick, bool)

    @property
    def completed(self) -> bool:
        return self.configured and len(self.history) == len(ORDER)

    def commit(self, hero_id: str | None) -> None:
        if hero_id is not None and (not isinstance(hero_id, str) or not hero_id):
            raise ValueError("Invalid hero identifier")
        action = self.current_action
        if action is None:
            raise ValueError("Draft is not started or is already complete")
        if hero_id is None and action.mode != "ban":
            raise ValueError("Only bans can be skipped")
        self.assign(action.group, action.index, hero_id)
        self.history.append(hero_id)

    def undo(self) -> None:
        if self.history:
            self.history.pop()
            action = self.current_action
            self.assign(action.group, action.index, None)

    @classmethod
    def from_dict(cls, value: dict, heroes: set[str], maps: set[str]) -> "DraftState":
        state = cls()
        if value.get("version") != 2:
            raise ValueError("Unsupported draft version")
        if value.get("map_id") is not None and value["map_id"] not in maps:
            raise ValueError("Unknown map")
        state.map_id = value.get("map_id")
        state.first_pick = value.get("first_pick")
        if state.first_pick is not None and not isinstance(state.first_pick, bool):
            raise ValueError("Invalid first-pick team")
        history = value.get("history")
        if not isinstance(history, list) or len(history) > len(ORDER):
            raise ValueError("Invalid draft history")
        for hero_id in history:
            if hero_id is not None and hero_id not in heroes:
                raise ValueError("Unknown hero")
            state.commit(hero_id)
        if state.slots != value["slots"]:
            raise ValueError("Slots do not match draft history")
        return state
