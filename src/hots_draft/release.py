"""Bump the version and push a release tag to the GitHub build workflow."""

import argparse
import re
import subprocess
from pathlib import Path

from hots_draft._version import VERSION

REPOSITORY = "https://github.com/MatthieuMv/hots-draft.git"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a version through GitHub Actions"
    )
    parser.add_argument("version", help="Stable version, e.g. 0.2.0")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        parser.error("Use a stable major.minor.patch version")
    if tuple(map(int, version.split("."))) <= tuple(map(int, VERSION.split("."))):
        parser.error(f"Version must be newer than {VERSION}")
    root = Path(__file__).resolve().parents[2]
    if git(root, "status", "--porcelain"):
        parser.error("Commit your changes first; releases require a clean working tree")
    if git(root, "remote", "get-url", "origin").removesuffix("/") not in (
        REPOSITORY,
        REPOSITORY.removesuffix(".git"),
        "git@github.com:MatthieuMv/hots-draft.git",
    ):
        parser.error("origin must point to MatthieuMv/hots-draft")
    branch = git(root, "branch", "--show-current")
    if branch not in ("main", "master"):
        parser.error("Release from main or master")
    tag = "v" + version
    if git(root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        parser.error(f"Release tag {tag} already exists")
    project = root / "pyproject.toml"
    project.write_text(
        re.sub(
            r'(?m)^version = "[^"]+"$',
            f'version = "{version}"',
            project.read_text(encoding="utf-8"),
            count=1,
        ),
        encoding="utf-8",
    )
    (root / "src/hots_draft/_version.py").write_text(
        f'VERSION = "{version}"\n', encoding="utf-8"
    )
    subprocess.run(["uv", "lock"], cwd=root, check=True)
    git(root, "add", "pyproject.toml", "uv.lock", "src/hots_draft/_version.py")
    git(root, "commit", "-m", f"Release {tag}")
    git(root, "tag", "-a", tag, "-m", f"Nexus Draft {tag}")
    # Atomic push avoids publishing a tag without its main-branch commit.
    git(root, "push", "--atomic", "origin", branch, tag)
    print("Release build queued: https://github.com/MatthieuMv/hots-draft/actions")
    print(
        f"When successful: https://github.com/MatthieuMv/hots-draft/releases/tag/{tag}"
    )


if __name__ == "__main__":
    main()
