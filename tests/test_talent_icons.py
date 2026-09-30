import httpx

from hots_draft import talent_icons


def hero():
    return {
        "source": {"url": "https://www.icy-veins.com/heroes/jaina-build-guide"},
        "builds": [
            {"talent_tiers": [{"talents": [{"id": "talent", "name": "Talent"}]}]}
        ],
    }


def test_old_snapshot_discovers_icon_and_reuses_cache(tmp_path, monkeypatch):
    pages = []

    class Fetch:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __call__(self, url):
            pages.append(url)
            return '<div class="heroes_build_talent_tier"><a data-heroes-tooltip="talent"><img src="https://static.icy-veins.com/images/heroes/abilities/jaina-frostbolt.jpg"></a></div>'

    monkeypatch.setattr(talent_icons, "HttpFetcher", Fetch)
    requests = []

    def respond(request):
        requests.append(request.url)
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"fake image")

    client = httpx.Client
    monkeypatch.setattr(
        talent_icons.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    assert talent_icons.download_talent_icons(tmp_path, hero()) == 1
    assert talent_icons.icon_path(tmp_path, "talent").exists()
    assert talent_icons.download_talent_icons(tmp_path, hero()) == 0
    assert len(pages) == len(requests) == 1


def test_artwork_urls_and_cache_paths_are_constrained(tmp_path):
    assert talent_icons.trusted_icon_url("https://evil.test/icon.png") is None
    assert (
        talent_icons.trusted_icon_url("https://static.icy-veins.com/not-an-icon")
        is None
    )
    assert talent_icons.icon_path(tmp_path, "../../escape").parent == tmp_path
    assert talent_icons.download_talent_icons(tmp_path, hero(), lambda: True) == 0
