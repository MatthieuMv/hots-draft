"""Refresh artwork on the publisher's machine before committing/building."""

from pathlib import Path

from hots_draft.portraits import download_portraits
from hots_draft.scraper import ensure_data_ready, load_heroes
from hots_draft.talent_icons import download_talent_icons, icon_path


def validate_assets(root: Path, heroes: dict) -> None:
    missing = {
        id_ for id_ in heroes if not (root / "portraits" / f"{id_}.jpg").exists()
    }
    missing |= {
        t["id"]
        for hero in heroes.values()
        for build in hero["builds"]
        for tier in build["talent_tiers"]
        for t in tier["talents"]
        if not icon_path(root / "talent-icons", t["id"]).exists()
    }
    if missing:
        raise RuntimeError(
            f"Missing {len(missing)} artwork files. Run uv run hots-assets before building."
        )


def main():
    root = Path(__file__).resolve().parents[2] / "data"
    heroes = load_heroes(ensure_data_ready(root))
    download_portraits(root / "portraits", set(heroes))
    for index, (hero_id, hero) in enumerate(heroes.items(), 1):
        count = download_talent_icons(root / "talent-icons", hero)
        print(f"{index}/{len(heroes)} {hero_id}: {count} icons downloaded")
    validate_assets(root, heroes)


if __name__ == "__main__":
    main()
