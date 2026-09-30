"""Optional, persistent talent artwork cache sourced from guide markup."""

import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from hots_draft.scraper import BASE_URL, USER_AGENT, HttpFetcher, atomic_write


def icon_path(directory: Path, talent_id: str) -> Path:
    return directory / (hashlib.sha256(talent_id.encode()).hexdigest() + ".png")


def trusted_icon_url(value: str) -> str | None:
    url = urljoin(BASE_URL, value)
    parts = urlsplit(url)
    if (
        parts.scheme == "https"
        and parts.hostname == "static.icy-veins.com"
        and parts.path.startswith("/images/heroes/")
    ):
        return url
    return None


def download_talent_icons(directory: Path, hero: dict, cancelled=lambda: False) -> int:
    talents = {
        t["id"]: t
        for b in hero["builds"]
        for tier in b["talent_tiers"]
        for t in tier["talents"]
    }
    missing = {
        id_: t for id_, t in talents.items() if not icon_path(directory, id_).exists()
    }
    if not missing or cancelled():
        return 0
    sources = {
        id_: trusted_icon_url(t.get("icon_url", "")) for id_, t in missing.items()
    }
    if any(not url for url in sources.values()):
        # Older snapshots did not retain artwork URLs; discover them lazily.
        with HttpFetcher() as fetch:
            soup = BeautifulSoup(fetch(hero["source"]["url"]), "html.parser")
        for link in soup.select(".heroes_build_talent_tier a[data-heroes-tooltip]"):
            image = link.select_one("img[src]")
            id_ = link["data-heroes-tooltip"]
            if id_ in missing and image:
                sources[id_] = trusted_icon_url(image["src"])
    count = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10) as client:
        for id_, url in sources.items():
            if cancelled():
                break
            if not url:
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                data = response.content
                if len(data) > 2_000_000 or not data.startswith(
                    (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
                ):
                    continue
                atomic_write(icon_path(directory, id_), data)
                count += 1
            except (httpx.HTTPError, OSError):
                continue
    return count
