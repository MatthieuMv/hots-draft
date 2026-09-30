import json
from pathlib import Path

import httpx
import pytest

from hots_draft import scraper

HTML = (Path(__file__).parent / "fixtures" / "jaina.html").read_text(encoding="utf-8")
JAINA = {"id": "jaina", "name": "Jaina", "url": scraper.BASE_URL + "jaina-build-guide"}
INDEX = """<div class="nav_content_block_entry_heroes_hero"><a href="//www.icy-veins.com/heroes/jaina-build-guide"><span>Jaina</span></a></div>
<div class="nav_content_block_entry_heroes_hero"><a href="/heroes/johanna-build-guide"><span>Johanna</span></a></div>
<div class="nav_content_block_entry_heroes_hero"><a href="/heroes/alarak-build-guide"><span>Alarak</span></a></div>"""


def fake_fetch(url):
    if url == scraper.BASE_URL:
        return INDEX
    slug = scraper.canonical_hero_url(url)[0]
    return HTML.replace("Jaina", slug.title()).replace("jaina", slug)


def test_parse_requested_fields_and_talent_alternatives():
    hero = scraper.parse_hero(HTML, JAINA)
    assert hero["overview"] == "Jaina deals burst damage."
    assert hero["strengths"] == ["Excellent waveclear"]
    assert hero["weaknesses"] == ["Limited mobility"]
    assert hero["role"] == "Ranged Assassin"
    assert hero["synergies"]["heroes"] == [{"id": "johanna", "name": "Johanna"}]
    assert hero["counters"]["heroes"] == [{"id": "alarak", "name": "Alarak"}]
    assert hero["maps"]["weaker"] == []
    assert hero["maps"]["stronger"][0]["id"] == "infernal-shrines"
    build = hero["builds"][0]
    assert [tier["level"] for tier in build["talent_tiers"]] == [
        1,
        4,
        7,
        10,
        13,
        16,
        20,
    ]
    assert [
        (t["name"], t["recommended"]) for t in build["talent_tiers"][0]["talents"]
    ] == [("Fingers of Frost", True), ("Winter's Reach", False)]
    assert build["calculator_url"].endswith("#23.0!3112322")
    assert build["description"] == "Improve Frostbolt damage."
    assert hero["source"]["updated_at"] == "2026-03-16T02:45:00+00:00"


def test_discovery_deduplicates_and_rejects_external_and_nonroster_links():
    html = INDEX + INDEX + '<a href="/heroes/fake-build-guide">fake</a>'
    html += '<div class="nav_content_block_entry_heroes_hero"><a href="https://evil.example/heroes/fake-build-guide"><span>Fake</span></a></div>'
    assert [hero["id"] for hero in scraper.discover_heroes(html)] == [
        "alarak",
        "jaina",
        "johanna",
    ]


def test_roster_short_name_accepts_full_guide_name():
    hero = {
        "id": "deckard",
        "name": "Deckard",
        "url": scraper.BASE_URL + "deckard-build-guide",
    }
    html = HTML.replace("Jaina Build Guide", "Deckard Cain Build Guide").replace(
        "jaina", "deckard"
    )
    assert scraper.parse_hero(html, hero)["name"] == "Deckard"


def test_chromie_talent_levels_are_preserved():
    html = HTML
    for original, actual in [(4, 2), (7, 5), (10, 8), (13, 11), (16, 14), (20, 18)]:
        html = html.replace(f"Level {original}<", f"Level {actual}<")
    hero = scraper.parse_hero(html, JAINA)
    assert [tier["level"] for tier in hero["builds"][0]["talent_tiers"]] == [
        1,
        2,
        5,
        8,
        11,
        14,
        18,
    ]


def test_unclosed_overview_paragraph_does_not_absorb_other_sections():
    html = HTML.replace("damage.</p>", "damage.<p>")
    assert scraper.parse_hero(html, JAINA)["overview"] == "Jaina deals burst damage."


@pytest.mark.parametrize(
    "broken",
    [
        "<h1>Just a moment...</h1>",
        HTML.replace('class="heroes_maps_weaker"', 'class="changed"'),
        HTML.replace('<span class="heroes_maps_empty">None</span>', ""),
        HTML.replace('class="heroes_build_talent_tier_recommended"', 'class="changed"'),
    ],
)
def test_incomplete_source_is_rejected(broken):
    with pytest.raises(scraper.ScrapeError):
        scraper.parse_hero(broken, JAINA)


def test_initialize_and_cached_startup_are_offline(tmp_path):
    snapshot = scraper.ensure_data_ready(tmp_path, fetcher=fake_fetch)
    assert scraper.dataset_ready(tmp_path)
    assert len(scraper.load_heroes(snapshot)) == 3
    lines = (snapshot / "heroes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[1])["id"] == "jaina"

    def forbidden(_):
        pytest.fail("Ready startup attempted network access")

    assert scraper.ensure_data_ready(tmp_path, fetcher=forbidden) == snapshot


def test_interrupted_initialization_resumes(tmp_path):
    calls = []

    def interrupted(url):
        calls.append(url)
        if url.endswith("jaina-build-guide"):
            raise scraper.ScrapeError("Network interrupted")
        return fake_fetch(url)

    with pytest.raises(scraper.ScrapeError):
        scraper.ensure_data_ready(tmp_path, fetcher=interrupted)
    assert not scraper.dataset_ready(tmp_path)
    assert not (tmp_path / "manifest.json").exists()
    calls.clear()

    def resumed(url):
        calls.append(url)
        return fake_fetch(url)

    scraper.ensure_data_ready(tmp_path, fetcher=resumed)
    assert scraper.dataset_ready(tmp_path)
    assert not any(url.endswith("alarak-build-guide") for url in calls)


def test_corruption_is_detected_and_repaired(tmp_path):
    snapshot = scraper.ensure_data_ready(tmp_path, fetcher=fake_fetch)
    (snapshot / "heroes" / "jaina.json").write_text("{}", encoding="utf-8")
    assert not scraper.dataset_ready(tmp_path)
    replacement = scraper.ensure_data_ready(tmp_path, fetcher=fake_fetch)
    assert replacement != snapshot
    assert scraper.dataset_ready(tmp_path)


def test_failed_refresh_preserves_published_dataset(tmp_path):
    snapshot = scraper.ensure_data_ready(tmp_path, fetcher=fake_fetch)
    manifest = (tmp_path / "manifest.json").read_bytes()

    def blocked(_):
        raise scraper.ScrapeError("403")

    with pytest.raises(scraper.ScrapeError):
        scraper.ensure_data_ready(tmp_path, refresh=True, fetcher=blocked)
    assert (tmp_path / "manifest.json").read_bytes() == manifest
    assert scraper.dataset_ready(tmp_path)
    assert scraper.ensure_data_ready(tmp_path, fetcher=blocked) == snapshot


def test_unknown_relationship_prevents_publication(tmp_path):
    def unknown(url):
        return (
            fake_fetch(url).replace("johanna-build-guide", "unknown-build-guide")
            if url != scraper.BASE_URL
            else INDEX
        )

    with pytest.raises(scraper.ScrapeError, match="missing from the roster"):
        scraper.ensure_data_ready(tmp_path, fetcher=unknown)
    assert not scraper.dataset_ready(tmp_path)


def test_html_directory_import(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text(INDEX, encoding="utf-8")
    for hero in scraper.discover_heroes(INDEX):
        (source / f"{hero['id']}.html").write_text(
            fake_fetch(hero["url"]), encoding="utf-8"
        )
    scraper.ensure_data_ready(
        tmp_path / "data", fetcher=scraper.HtmlDirectoryFetcher(source)
    )
    assert scraper.dataset_ready(tmp_path / "data")


def test_http_block_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(403)

    with scraper.HttpFetcher(delay=0) as fetch:
        fetch.client.close()
        fetch.client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(scraper.ScrapeError, match="Access blocked"):
            fetch(scraper.BASE_URL)
    assert calls == ["/robots.txt", "/heroes/"]


def test_transient_errors_are_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, text="<html>ok</html>", headers={"content-type": "text/html"}
        )

    with scraper.HttpFetcher(delay=0) as fetch:
        fetch.client.close()
        fetch.client = httpx.Client(transport=httpx.MockTransport(handler))
        assert fetch._request(scraper.BASE_URL) == "<html>ok</html>"
    assert len(calls) == 2


def test_robots_disallow_is_respected():
    with scraper.HttpFetcher(delay=0) as fetch:
        fetch.client.close()
        fetch.client = httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text="User-agent: *\nDisallow: /heroes/")
            )
        )
        with pytest.raises(scraper.ScrapeError, match="robots.txt disallows"):
            fetch(scraper.BASE_URL)
