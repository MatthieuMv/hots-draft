"""Build the desktop executable with: uv run --group build hots-build."""

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Nexus Draft executable")
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
    run(
        [
            str(root / "tools" / "executable_entry.py"),
            "--name",
            "NexusDraft",
            "--onedir" if args.onedir else "--onefile",
            "--windowed",
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
