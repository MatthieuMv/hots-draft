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


def rank_picked_heroes(heroes: dict, draft: DraftState) -> list[Recommendation]:
    """Evaluate each picked hero against their teammates and opposing team."""
    results = []
    for side in ("allies", "enemies"):
        for index, hero_id in enumerate(draft.slots[side]):
            if hero_id not in heroes:
                continue
            context = deepcopy(draft)
            context.slots[side][index] = None
            result = next(
                result
                for result in rank_heroes(heroes, context, side=side, include_all=True)
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
            result.score += 3 if mode == "pick" else 2
            result.reasons.append("Strong on this battleground")
        elif weak:
            result.score -= 3 if mode == "pick" else 2
            result.warnings.append("Weaker on this battleground")
        synergy = references(hero, "synergies")
        counters = references(hero, "counters")
        if mode == "pick":
            for friend in friends:
                if friend in synergy or id_ in references(heroes[friend], "synergies"):
                    result.score += 4
                    result.reasons.append(f"Pairs with {heroes[friend]['name']}")
            for opponent in opponents:
                if id_ in references(heroes[opponent], "counters"):
                    result.score += 5
                    result.reasons.append(f"Counters {heroes[opponent]['name']}")
                if opponent in counters:
                    result.score -= 6
                    result.warnings.append(f"Threatened by {heroes[opponent]['name']}")
            if friends and len(friends) < 5 and hero["role"] in ("Tank", "Healer"):
                if hero["role"] not in roles:
                    result.score += 2
                    result.reasons.append(
                        f"Adds a missing {hero['role'].lower()} to the team"
                    )
                else:
                    result.score -= 2
                    result.warnings.append(f"Team already has a {hero['role'].lower()}")
        else:
            for friend in friends:
                if id_ in references(heroes[friend], "counters"):
                    result.score += 6
                    result.reasons.append(
                        f"Protects {heroes[friend]['name']} from a listed counter"
                    )
                if friend in counters:
                    result.score -= 3
                    result.warnings.append(
                        f"Already countered by {heroes[friend]['name']}"
                    )
            for opponent in opponents:
                if opponent in synergy or id_ in references(
                    heroes[opponent], "synergies"
                ):
                    result.score += 4
                    result.reasons.append(
                        f"Denies synergy with {heroes[opponent]['name']}"
                    )
        if include_all or (result.score > 0 and result.reasons):
            results.append(result)
    return sorted(
        results, key=lambda result: (-result.score, heroes[result.hero_id]["name"])
    )
