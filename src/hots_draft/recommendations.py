"""Explainable guide-based rankings; scores are heuristics, not win probabilities."""

from copy import deepcopy
from dataclasses import dataclass, field

from hots_draft.draft import DraftState


@dataclass
class Recommendation:
    hero_id: str
    score: float = 0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)

    def add(self, value, effect, subject, subject_id, label):
        self.score += value
        (self.reasons if value > 0 else self.warnings).append(label)
        self.signals.append(
            {
                "value": value,
                "effect": effect,
                "subject": subject,
                "id": subject_id,
                "label": label,
            }
        )


def rank_picked_heroes(
    heroes: dict, draft: DraftState, *, include_bans=False
) -> list[Recommendation]:
    """Evaluate each picked hero against their teammates and opposing team."""
    results = []
    for group in ("allies", "enemies", "ally_bans", "enemy_bans"):
        if not include_bans and "bans" in group:
            continue
        side = "allies" if group in ("allies", "ally_bans") else "enemies"
        for index, hero_id in enumerate(draft.slots[group]):
            if hero_id not in heroes:
                continue
            context = deepcopy(draft)
            context.slots[group][index] = None
            result = next(
                result
                for result in rank_heroes(
                    heroes,
                    context,
                    side=side,
                    mode="ban" if "bans" in group else "pick",
                    include_all=True,
                )
                if result.hero_id == hero_id
            )
            results.append(result)
    return sorted(
        results, key=lambda result: (-result.score, heroes[result.hero_id]["name"])
    )


def references(hero: dict, field: str) -> set[str]:
    return {ref["id"] for ref in hero[field]["heroes"]}


def rank_heroes(
    heroes: dict[str, dict],
    draft: DraftState,
    *,
    mode: str = "pick",
    side: str = "allies",
    include_all: bool = False,
) -> list[Recommendation]:
    if mode not in ("pick", "ban") or side not in ("allies", "enemies"):
        raise ValueError("Unknown recommendation mode or team")
    friends = [id_ for id_ in draft.slots[side] if id_ in heroes]
    opponents = [
        id_
        for id_ in draft.slots["enemies" if side == "allies" else "allies"]
        if id_ in heroes
    ]
    if not include_all and not draft.map_id and not friends and not opponents:
        return []
    roles = [heroes[id_]["role"] for id_ in friends]
    results = []
    for id_, hero in heroes.items():
        if id_ in draft.unavailable:
            continue
        result = Recommendation(id_)
        strong = draft.map_id in {ref["id"] for ref in hero["maps"]["stronger"]}
        weak = draft.map_id in {ref["id"] for ref in hero["maps"]["weaker"]}
        if strong:
            result.add(
                3 if mode == "pick" else 2,
                "positive",
                "map",
                draft.map_id,
                "Strong on this battleground",
            )
        elif weak:
            result.add(
                -3 if mode == "pick" else -2,
                "negative",
                "map",
                draft.map_id,
                "Weaker on this battleground",
            )
        synergy = references(hero, "synergies")
        counters = references(hero, "counters")
        if mode == "pick":
            for friend in friends:
                if friend in synergy or id_ in references(heroes[friend], "synergies"):
                    result.add(
                        4,
                        "synergy",
                        "hero",
                        friend,
                        f"Pairs with {heroes[friend]['name']}",
                    )
            for opponent in opponents:
                if id_ in references(heroes[opponent], "counters"):
                    result.add(
                        5,
                        "counter",
                        "hero",
                        opponent,
                        f"Counters {heroes[opponent]['name']}",
                    )
                if opponent in counters:
                    result.add(
                        -6,
                        "counter",
                        "hero",
                        opponent,
                        f"Threatened by {heroes[opponent]['name']}",
                    )
            if friends and len(friends) < 5 and hero["role"] in ("Tank", "Healer"):
                if hero["role"] not in roles:
                    result.add(
                        2,
                        "positive",
                        "hero",
                        id_,
                        f"Adds a missing {hero['role'].lower()} to the team",
                    )
                else:
                    result.add(
                        -2,
                        "negative",
                        "hero",
                        id_,
                        f"Team already has a {hero['role'].lower()}",
                    )
        else:
            for friend in friends:
                if id_ in references(heroes[friend], "counters"):
                    result.add(
                        6,
                        "counter",
                        "hero",
                        friend,
                        f"Protects {heroes[friend]['name']} from a listed counter",
                    )
                if friend in counters:
                    result.add(
                        -3,
                        "counter",
                        "hero",
                        friend,
                        f"Already countered by {heroes[friend]['name']}",
                    )
            for opponent in opponents:
                if opponent in synergy or id_ in references(
                    heroes[opponent], "synergies"
                ):
                    result.add(
                        4,
                        "synergy",
                        "hero",
                        opponent,
                        f"Denies synergy with {heroes[opponent]['name']}",
                    )
        if include_all or (result.score > 0 and result.reasons):
            results.append(result)
    return sorted(
        results, key=lambda result: (-result.score, heroes[result.hero_id]["name"])
    )
