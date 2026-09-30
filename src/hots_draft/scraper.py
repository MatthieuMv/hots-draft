"""Scrape Icy Veins hero guides into a versioned, agent-readable dataset.

Call ensure_data_ready() before starting the overlay, then load_heroes().
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag
from filelock import FileLock

BASE_URL = "https://www.icy-veins.com/heroes/"
SCHEMA_VERSION = 1
DEFAULT_DATA_DIR = Path.cwd() / "data"
USER_AGENT = "HotsDraftData/0.1 (+local Heroes of the Storm draft helper)"
LOG = logging.getLogger(__name__)
HERO_PATH = re.compile(r"^/heroes/([a-z0-9-]+)-build-guide/?$")


class ScrapeError(RuntimeError):
    """Fetching or parsing failed; a complete dataset cannot be published."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text() if node else "").strip()


def required(node: Tag | BeautifulSoup, selector: str) -> Tag:
    result = node.select_one(selector)
    if result is None:
        raise ScrapeError(f"Required source markup missing: {selector}")
    return result


def canonical_hero_url(href: str) -> tuple[str, str] | None:
    url = urljoin(BASE_URL, href)
    parts = urlsplit(url)
    match = HERO_PATH.fullmatch(parts.path)
    if parts.hostname != "www.icy-veins.com" or parts.scheme != "https" or not match:
        return None
    return match[1], f"{BASE_URL}{match[1]}-build-guide"


def discover_heroes(html: str) -> list[dict]:
    """Use the hero navigation roster, excluding news and unrelated guides."""
    soup = BeautifulSoup(html, "html.parser")
    heroes = {}
    for link in soup.select(".nav_content_block_entry_heroes_hero a[href]"):
        ref = canonical_hero_url(link["href"])
        if ref:
            name = text(link.select_one("span"))
            if not name:
                raise ScrapeError(f"Missing hero name for {ref[0]}")
            heroes[ref[0]] = {"id": ref[0], "name": name, "url": ref[1]}
    if not heroes:
        raise ScrapeError(
            "No hero roster found. The index may be blocked or its markup changed."
        )
    return sorted(heroes.values(), key=lambda hero: hero["id"])


def section(soup: BeautifulSoup, suffix: str) -> BeautifulSoup:
    heading = soup.find("h2", id=re.compile(re.escape(suffix) + r"$"))
    if heading is None:
        raise ScrapeError(f"Missing section: {suffix}")
    anchor = (
        heading.parent
        if "heading_container" in heading.parent.get("class", [])
        else heading
    )
    nodes = []
    for sibling in anchor.next_siblings:
        if isinstance(sibling, Tag):
            if sibling.name == "h2" or sibling.find("h2"):
                break
            nodes.append(str(sibling))
    return BeautifulSoup("".join(nodes), "html.parser")


def paragraphs(node: Tag | BeautifulSoup) -> str:
    return "\n\n".join(text(p) for p in node.select("p") if text(p))


def hero_relations(node: Tag) -> dict:
    refs = {}
    # Only portrait links are explicit recommendations; prose mentions are context.
    for image in node.select("img.hero_portrait"):
        link = image.find_parent("a", href=True)
        ref = canonical_hero_url(link["href"]) if link else None
        if not ref:
            raise ScrapeError("Invalid hero portrait link")
        name = image.get("title") or re.sub(r" Portrait$", "", image.get("alt", ""))
        if not name:
            raise ScrapeError("Missing hero portrait name")
        refs[ref[0]] = {"id": ref[0], "name": name}
    if not refs and not re.search(r"\bnone\b", text(node), re.IGNORECASE):
        raise ScrapeError("Empty hero relationship group without an explicit None")
    return {"heroes": list(refs.values()), "explanation": paragraphs(node)}


def parse_build(node: Tag) -> dict:
    tiers = []
    for tier in node.select(".heroes_build_talent_tier"):
        level = re.search(
            r"Level\s+(\d+)", text(required(tier, ".heroes_build_talent_tier_subtitle"))
        )
        if not level:
            raise ScrapeError("Missing talent level")
        choices = []
        for link in tier.select("a[data-heroes-tooltip]"):
            image = required(link, "img[alt]")
            name = re.sub(r" Icon$", "", image["alt"])
            choices.append(
                {
                    "id": link["data-heroes-tooltip"],
                    "name": name,
                    "recommended": "heroes_build_talent_tier_recommended"
                    in link.get("class", []),
                    "url": urljoin(BASE_URL, link["href"]),
                    "icon_url": urljoin(BASE_URL, image["src"])
                    if image.get("src")
                    else None,
                }
            )
        if not choices or not any(choice["recommended"] for choice in choices):
            raise ScrapeError(f"Missing recommended talent at level {level[1]}")
        tiers.append({"level": int(level[1]), "talents": choices})
    if len(tiers) != 7 or len({tier["level"] for tier in tiers}) != len(tiers):
        raise ScrapeError("Missing or duplicate talent tiers")
    calculator = node.select_one(".heroes_build_talent_calculator_url a[href]")
    return {
        "name": text(required(node, "h3")),
        "label": text(node.select_one(".heroes_build_tag")) or None,
        "description": paragraphs(required(node, ".heroes_build_text")),
        "talent_tiers": tiers,
        "calculator_url": urljoin(BASE_URL, calculator["href"]) if calculator else None,
    }


def parse_hero(html: str, hero: dict) -> dict:
    """Extract requested fields, rejecting incomplete and challenge pages."""
    # Some guides have unclosed <p> tags; HTML5 parsing restores browser boundaries.
    soup = BeautifulSoup(html, "html5lib")
    title = text(required(soup, "h1"))
    # The roster calls Deckard Cain "Deckard"; guides may use the full name.
    title_name = title.split(" Build Guide", 1)[0]
    if " Build Guide" not in title or not (
        title_name == hero["name"] or title_name.startswith(hero["name"] + " ")
    ):
        raise ScrapeError(f"Unexpected page title for {hero['id']}: {title}")
    overview = paragraphs(section(soup, "-overview"))
    strengths = [text(li) for li in required(soup, ".strengths").select("li")]
    weaknesses = [text(li) for li in required(soup, ".weaknesses").select("li")]
    maps = {}
    for rating in ("stronger", "average", "weaker"):
        group = required(soup, f".heroes_maps_{rating}")
        refs = {}
        for link in group.select("a[data-heroes-tooltip]"):
            image = required(link, "img[alt]")
            map_id = link["data-heroes-tooltip"].removeprefix("map-")
            refs[map_id] = {"id": map_id, "name": image.get("title") or image["alt"]}
        if not refs and not group.select_one(".heroes_maps_empty"):
            raise ScrapeError(f"Empty {rating} maps without an explicit None")
        maps[rating] = list(refs.values())
    maps["explanation"] = paragraphs(required(soup, ".heroes_maps_text"))
    builds = [parse_build(node) for node in soup.select(".heroes_build")]
    if not overview or not strengths or not weaknesses or not builds:
        raise ScrapeError(f"Incomplete required fields for {hero['id']}")
    metadata = soup.select_one(".page_author")
    updated = metadata.select_one("[data-time]") if metadata else None
    timestamp = updated.get("data-time", "") if updated else ""
    source_updated = (
        datetime.fromtimestamp(int(timestamp), UTC).isoformat()
        if timestamp.isdigit()
        else None
    )
    welcome = next(
        (text(p) for p in soup.select("p") if "Welcome to our guide for" in text(p)), ""
    )
    role = re.search(r", (?:a|an) (.*?) in Heroes of the Storm", welcome)
    result = {
        "schema_version": SCHEMA_VERSION,
        "id": hero["id"],
        "name": hero["name"],
        "role": role[1] if role else None,
        "overview": overview,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "synergies": hero_relations(required(soup, ".heroes_synergies")),
        "counters": hero_relations(required(soup, ".heroes_counters")),
        "maps": maps,
        "builds": builds,
        "source": {
            "url": hero["url"],
            "site": "Icy Veins",
            "retrieved_at": now(),
            "updated_at": source_updated,
            "author_line": text(metadata),
        },
    }
    validate_hero(result)
    return result


def validate_hero(hero: dict) -> None:
    """Validate stored documents as well as new parse results."""
    try:
        _validate_hero(hero)
    except (KeyError, TypeError, AttributeError) as error:
        raise ScrapeError(f"Malformed hero document: {error}") from error


def _validate_hero(hero: dict) -> None:
    if hero["schema_version"] != SCHEMA_VERSION or not re.fullmatch(
        r"[a-z0-9-]+", hero["id"]
    ):
        raise ScrapeError("Invalid hero schema or id")
    if hero["role"] is not None and not isinstance(hero["role"], str):
        raise ScrapeError("Invalid role")
    for field in ("name", "overview"):
        if not isinstance(hero[field], str) or not hero[field]:
            raise ScrapeError(f"Invalid {field}")
    for field in ("strengths", "weaknesses"):
        if (
            not isinstance(hero[field], list)
            or not hero[field]
            or not all(isinstance(x, str) and x for x in hero[field])
        ):
            raise ScrapeError(f"Invalid {field}")
    for field in ("synergies", "counters"):
        if not isinstance(hero[field]["heroes"], list) or not isinstance(
            hero[field]["explanation"], str
        ):
            raise ScrapeError("Invalid relationship group")
        for ref in hero[field]["heroes"]:
            if (
                not isinstance(ref["name"], str)
                or not ref["name"]
                or not re.fullmatch(r"[a-z0-9-]+", ref["id"])
            ):
                raise ScrapeError("Invalid relationship")
    map_ids = []
    if not isinstance(hero["maps"]["explanation"], str):
        raise ScrapeError("Invalid map explanation")
    for rating in ("stronger", "average", "weaker"):
        if not isinstance(hero["maps"][rating], list):
            raise ScrapeError("Invalid map group")
        for ref in hero["maps"][rating]:
            if (
                not isinstance(ref["name"], str)
                or not ref["name"]
                or not re.fullmatch(r"[a-z0-9-]+", ref["id"])
            ):
                raise ScrapeError("Invalid map reference")
        map_ids.extend(ref["id"] for ref in hero["maps"][rating])
    if not map_ids or len(map_ids) != len(set(map_ids)):
        raise ScrapeError("Missing or conflicting map ratings")
    if not isinstance(hero["builds"], list) or not hero["builds"]:
        raise ScrapeError("Missing builds")
    for build in hero["builds"]:
        if (
            not isinstance(build["name"], str)
            or not build["name"]
            or len(build["talent_tiers"]) != 7
        ):
            raise ScrapeError("Incomplete build")
        if not isinstance(build["description"], str) or (
            build["label"] is not None and not isinstance(build["label"], str)
        ):
            raise ScrapeError("Invalid build description or label")
        if build["calculator_url"] is not None and not isinstance(
            build["calculator_url"], str
        ):
            raise ScrapeError("Invalid calculator URL")
        levels = [tier["level"] for tier in build["talent_tiers"]]
        if len(set(levels)) != 7:
            raise ScrapeError("Duplicate talent levels")
        for tier in build["talent_tiers"]:
            if not isinstance(tier["level"], int) or not tier["talents"]:
                raise ScrapeError("Incomplete talent tier")
            for talent in tier["talents"]:
                if not all(
                    isinstance(talent[field], str) and talent[field]
                    for field in ("id", "name", "url")
                ) or not isinstance(talent["recommended"], bool):
                    raise ScrapeError("Invalid talent")
            if not any(
                t["recommended"] and t["name"] and t["id"] for t in tier["talents"]
            ):
                raise ScrapeError("Missing recommended talent")
    if canonical_hero_url(hero["source"]["url"]) != (
        hero["id"],
        f"{BASE_URL}{hero['id']}-build-guide",
    ):
        raise ScrapeError("Invalid source URL")
    for field in ("site", "retrieved_at", "author_line"):
        if not isinstance(hero["source"][field], str):
            raise ScrapeError("Invalid source metadata")
    if hero["source"]["updated_at"] is not None and not isinstance(
        hero["source"]["updated_at"], str
    ):
        raise ScrapeError("Invalid source update time")


class HttpFetcher:
    """Sequential, robots-aware HTTP access with bounded transient retries."""

    def __init__(self, delay: float = 1.0, retries: int = 3):
        if delay < 0 or retries < 0:
            raise ValueError("delay and retries must be nonnegative")
        self.delay, self.retries, self.last_request = delay, retries, 0.0
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
        )
        self.robots: RobotFileParser | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _request(self, url: str) -> str:
        for attempt in range(self.retries + 1):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.client.get(url)
                if response.status_code in (401, 403):
                    raise ScrapeError(
                        f"Access blocked (HTTP {response.status_code}) at {url}. "
                        "No data was marked ready. Use --html-dir with saved public HTML "
                        "or run from a network where the site permits requests."
                    )
                response.raise_for_status()
                if "text/html" not in response.headers.get(
                    "content-type", ""
                ) and not url.endswith("robots.txt"):
                    raise ScrapeError(f"Expected HTML from {url}")
                return response.text
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                transient = (
                    not isinstance(error, httpx.HTTPStatusError)
                    or error.response.status_code == 429
                    or error.response.status_code >= 500
                )
                if not transient or attempt == self.retries:
                    raise ScrapeError(f"Unable to fetch {url}: {error}") from error
                backoff = 2**attempt
                if isinstance(error, httpx.HTTPStatusError):
                    retry_after = error.response.headers.get("retry-after", "")
                    if retry_after.isdigit():
                        backoff = min(60, max(backoff, int(retry_after)))
                time.sleep(backoff)
        raise AssertionError("Unreachable")

    def __call__(self, url: str) -> str:
        if urlsplit(url).hostname != "www.icy-veins.com":
            raise ScrapeError("Fetcher is restricted to Icy Veins")
        if self.robots is None:
            self.robots = RobotFileParser()
            self.robots.parse(
                self._request("https://www.icy-veins.com/robots.txt").splitlines()
            )
            self.delay = max(self.delay, self.robots.crawl_delay(USER_AGENT) or 0)
        if not self.robots.can_fetch(USER_AGENT, url):
            raise ScrapeError(f"robots.txt disallows {url}")
        return self._request(url)


class HtmlDirectoryFetcher:
    """Offline import of index.html and <hero-id>.html saved from public guides."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def __call__(self, url: str) -> str:
        ref = canonical_hero_url(url)
        name = f"{ref[0]}.html" if ref else "index.html"
        try:
            return (self.directory / name).read_text(encoding="utf-8-sig")
        except OSError as error:
            raise ScrapeError(
                f"Cannot read {self.directory / name}: {error}"
            ) from error


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_ready(data_dir: Path | str = DEFAULT_DATA_DIR) -> bool:
    """Check completeness, hashes, and schema entirely offline."""
    root = Path(data_dir)
    try:
        manifest = read_json(root / "manifest.json")
        if (
            manifest["schema_version"] != SCHEMA_VERSION
            or manifest["status"] != "ready"
        ):
            return False
        generation = manifest["generation"]
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            return False
        snapshot = root / "snapshots" / generation
        roster = manifest["heroes"]
        if not roster or manifest["hero_count"] != len(roster):
            return False
        ids = [hero["id"] for hero in roster]
        if len(ids) != len(set(ids)) or any(
            not re.fullmatch(r"[a-z0-9-]+", id_) for id_ in ids
        ):
            return False
        expected = {f"heroes/{id_}.json" for id_ in ids} | {
            "heroes.jsonl",
            "draft-index.json",
        }
        if set(manifest["files"]) != expected:
            return False
        for relative, digest in manifest["files"].items():
            if hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() != digest:
                return False
        for id_ in ids:
            hero = read_json(snapshot / "heroes" / f"{id_}.json")
            validate_hero(hero)
            if hero["id"] != id_:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, ScrapeError):
        return False


def _initialize(root: Path, fetch: Callable[[str], str], refresh: bool) -> Path:
    roster = discover_heroes(fetch(BASE_URL))
    atomic_write(root / "pending-roster.json", encoded(roster))
    records = []
    for position, hero in enumerate(roster, 1):
        cache = root / ".cache" / f"{hero['id']}.json"
        record = None
        if not refresh and cache.exists():
            try:
                record = read_json(cache)
                validate_hero(record)
                if (
                    record["id"] != hero["id"]
                    or record["name"] != hero["name"]
                    or record["source"]["url"] != hero["url"]
                ):
                    record = None
            except (OSError, ValueError, KeyError, TypeError, ScrapeError):
                record = None
        if record is None:
            LOG.info("[%d/%d] Fetching %s", position, len(roster), hero["name"])
            record = parse_hero(fetch(hero["url"]), hero)
            atomic_write(cache, encoded(record))
        records.append(record)
    ids = {hero["id"] for hero in records}
    for hero in records:
        for field in ("synergies", "counters"):
            unknown = {ref["id"] for ref in hero[field]["heroes"]} - ids
            if unknown:
                raise ScrapeError(
                    f"{hero['id']} references heroes missing from the roster: {unknown}"
                )
    generation = uuid.uuid4().hex
    snapshot = root / "snapshots" / generation
    files = {}

    def save(relative: str, payload: bytes) -> None:
        atomic_write(snapshot / relative, payload)
        files[relative] = hashlib.sha256(payload).hexdigest()

    for hero in records:
        save(f"heroes/{hero['id']}.json", encoded(hero))
    save(
        "heroes.jsonl",
        (
            "\n".join(
                json.dumps(hero, ensure_ascii=False, separators=(",", ":"))
                for hero in records
            )
            + "\n"
        ).encode("utf-8"),
    )
    index = {
        hero["id"]: {
            "name": hero["name"],
            "role": hero["role"],
            "synergies": [ref["id"] for ref in hero["synergies"]["heroes"]],
            "countered_by": [ref["id"] for ref in hero["counters"]["heroes"]],
            "maps": {
                rating: [ref["id"] for ref in hero["maps"][rating]]
                for rating in ("stronger", "average", "weaker")
            },
            "build_names": [build["name"] for build in hero["builds"]],
            "file": f"heroes/{hero['id']}.json",
        }
        for hero in records
    }
    save("draft-index.json", encoded(index))
    # Publish last: failed or interrupted refreshes cannot expose partial snapshots.
    atomic_write(
        root / "manifest.json",
        encoded(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ready",
                "generated_at": now(),
                "source_url": BASE_URL,
                "generation": generation,
                "hero_count": len(records),
                "heroes": roster,
                "files": files,
            }
        ),
    )
    return snapshot


def ensure_data_ready(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    refresh: bool = False,
    fetcher: Callable[[str], str] | None = None,
    delay: float = 1.0,
) -> Path:
    """Return a complete snapshot, initializing missing/corrupt data first.

    A ready local snapshot makes zero network calls. Failed initializations raise
    ScrapeError and resume from validated cached heroes on the next attempt.
    Failed refreshes leave the previously published snapshot untouched.
    """
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / ".initialize.lock"), timeout=600):
        if not refresh and dataset_ready(root):
            return root / "snapshots" / read_json(root / "manifest.json")["generation"]
        if fetcher is not None:
            return _initialize(root, fetcher, refresh)
        with HttpFetcher(delay=delay) as fetch:
            return _initialize(root, fetch, refresh)


def load_heroes(snapshot: Path | str) -> dict[str, dict]:
    """Load a snapshot returned by ensure_data_ready, keyed by stable hero id."""
    root = Path(snapshot)
    index = read_json(root / "draft-index.json")
    return {id_: read_json(root / "heroes" / f"{id_}.json") for id_ in index}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch the current roster and every hero again",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        help="Import saved index.html and <hero-id>.html instead of HTTP",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Minimum seconds between HTTP requests"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        snapshot = ensure_data_ready(
            args.data_dir,
            refresh=args.refresh,
            fetcher=HtmlDirectoryFetcher(args.html_dir) if args.html_dir else None,
            delay=args.delay,
        )
    except (ScrapeError, OSError, ValueError) as error:
        print(f"Hero data initialization failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        f"Hero data ready: {len(read_json(snapshot / 'draft-index.json'))} heroes in {snapshot}"
    )


if __name__ == "__main__":
    main()
