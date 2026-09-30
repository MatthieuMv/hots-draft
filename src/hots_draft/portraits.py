"""Cache hero portraits linked by the public Icy Veins navigation."""

import logging
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from hots_draft.scraper import (
    BASE_URL,
    USER_AGENT,
    HttpFetcher,
    atomic_write,
    canonical_hero_url,
)


def download_portraits(
    directory: Path,
    hero_ids: set[str],
    on_ready=lambda _: None,
    cancelled=lambda: False,
) -> int:
    missing = {id_ for id_ in hero_ids if not (directory / f"{id_}.jpg").exists()}
    if not missing:
        return 0
    with HttpFetcher() as fetch:
        soup = BeautifulSoup(fetch(BASE_URL), "html.parser")
    sources = {}
    for link in soup.select(".nav_content_block_entry_heroes_hero a[href]"):
        ref = canonical_hero_url(link["href"])
        image = link.select_one("img[src]")
        if ref and image and ref[0] in missing:
            url = urljoin(BASE_URL, image["src"])
            parts = urlsplit(url)
            if (
                parts.scheme == "https"
                and parts.hostname == "static.icy-veins.com"
                and parts.path.startswith("/images/heroes/hero-portraits/")
            ):
                sources[ref[0]] = url
    downloaded = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10) as client:
        for id_, url in sources.items():
            if cancelled():
                break
            try:
                response = client.get(url)
                response.raise_for_status()
                content = response.content
                if (
                    not response.headers.get("content-type", "").startswith("image/")
                    or len(content) > 2_000_000
                    or not content.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"))
                ):
                    continue
                atomic_write(directory / f"{id_}.jpg", content)
                downloaded += 1
                on_ready(id_)
            except (httpx.HTTPError, OSError) as error:
                logging.getLogger(__name__).debug(
                    "Portrait unavailable for %s: %s", id_, error
                )
    return downloaded
