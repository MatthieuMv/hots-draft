"""Build the desktop executable with: uv run --group build hots-build."""

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the HotsDraft executable")
    parser.add_argument(
        "--onedir", action="store_true", help="Build a folder instead of one executable"
    )
    parser.add_argument("--output-dir", type=Path, help="Override the dist folder")
    args = parser.parse_args()
    from PyInstaller.__main__ import run

    runtime_args = []
    if sys.platform == "win32":
        # Qt uses Windows' ICU API. An unrelated ICU DLL on PATH (e.g. Poppler)
        # has incompatible exports and can be collected by PyInstaller instead.
        icu = Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll"
        runtime_args.extend(["--add-binary", f"{icu};."])

    root = Path(__file__).resolve().parents[2]
    from hots_draft.assets import validate_assets
    from hots_draft.scraper import dataset_ready, load_heroes

    data = root / "data"
    if not dataset_ready(data):
        parser.error(
            "Committed data is incomplete. Run uv run hots-scrape before building."
        )
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    snapshot = data / "snapshots" / manifest["generation"]
    validate_assets(data, load_heroes(snapshot))
    bundled = [
        (data / "manifest.json", "data"),
        (snapshot, f"data/snapshots/{manifest['generation']}"),
        (data / "portraits", "data/portraits"),
        (data / "talent-icons", "data/talent-icons"),
        (root / "assets", "assets"),
    ]
    separator = ";" if sys.platform == "win32" else ":"
    for source, destination in bundled:
        runtime_args.extend(["--add-data", f"{source}{separator}{destination}"])
    run(
        [
            str(root / "tools" / "executable_entry.py"),
            "--name",
            "HotsDraft",
            "--onedir" if args.onedir else "--onefile",
            "--windowed",
            "--icon",
            str(root / "assets/hots-draft.ico"),
            "--noconfirm",
            "--paths",
            str(root / "src"),
            "--distpath",
            str(args.output_dir.resolve() if args.output_dir else root / "dist"),
            "--workpath",
            str(root / "build" / "pyinstaller"),
            "--specpath",
            str(root / "build"),
            "--hidden-import",
            "html5lib.treebuilders.etree",
            *runtime_args,
        ]
    )


if __name__ == "__main__":
    main()
