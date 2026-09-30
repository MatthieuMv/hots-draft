from pathlib import Path

import pytest

from hots_draft.assets import validate_assets
from hots_draft.runtime_data import initialize_bundled_data
from hots_draft.scraper import ScrapeError, dataset_ready, load_heroes

BUNDLE = Path(__file__).resolve().parents[1] / "data"


def test_bundle_initializes_clean_host_and_preserves_session(tmp_path):
    session = tmp_path / "draft-session.json"
    session.write_text("saved session")
    snapshot = initialize_bundled_data(tmp_path, BUNDLE)
    assert dataset_ready(tmp_path)
    heroes = load_heroes(snapshot)
    assert heroes and "jaina" in heroes
    validate_assets(BUNDLE, heroes)
    assert session.read_text() == "saved session"
    (snapshot / "heroes/jaina.json").write_text("corrupt")
    initialize_bundled_data(tmp_path, BUNDLE)
    assert dataset_ready(tmp_path)
    assert session.read_text() == "saved session"


def test_incomplete_bundle_reports_error_without_scraping(tmp_path):
    with pytest.raises(ScrapeError, match="bundled hero data"):
        initialize_bundled_data(tmp_path / "host", tmp_path / "missing")


def test_packaged_loader_never_calls_scraper(tmp_path, monkeypatch):
    from hots_draft import overlay

    monkeypatch.setattr(overlay.sys, "frozen", True, raising=False)

    def forbidden(*args):
        raise AssertionError("Target host tried to scrape")

    monkeypatch.setattr(overlay, "ensure_data_ready", forbidden)
    loader = overlay.DataLoader(tmp_path)
    ready, errors = [], []
    loader.ready.connect(ready.append)
    loader.failed.connect(errors.append)
    loader.run()
    assert not errors
    assert ready and "jaina" in ready[0]
    assert dataset_ready(tmp_path)
