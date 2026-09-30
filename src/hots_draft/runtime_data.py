"""Initialize packaged apps from committed data without host-side scraping."""

import json
import shutil
import sys
from pathlib import Path

from filelock import FileLock

from hots_draft.scraper import ScrapeError, atomic_write, dataset_ready


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def initialize_bundled_data(destination: Path, bundle: Path | None = None) -> Path:
    bundle = bundle or resource_root() / "data"
    if not dataset_ready(bundle):
        raise ScrapeError("The bundled hero data is incomplete. Reinstall HotsDraft.")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    with FileLock(str(destination / ".initialize.lock"), timeout=600):
        ready = dataset_ready(destination)
        previous = (
            json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            if ready
            else {}
        )
        if not ready or manifest["generated_at"] > previous["generated_at"]:
            generation = manifest["generation"]
            shutil.copytree(
                bundle / "snapshots" / generation,
                destination / "snapshots" / generation,
                dirs_exist_ok=True,
            )
            atomic_write(
                destination / "manifest.json", (bundle / "manifest.json").read_bytes()
            )
            previous = manifest
        return destination / "snapshots" / previous["generation"]
