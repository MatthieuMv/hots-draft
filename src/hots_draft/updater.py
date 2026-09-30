"""Verified release downloads and Windows executable replacement."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from hots_draft._version import VERSION

REPO = "MatthieuMv/hots-draft"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
MAX_SIZE = 512 * 1024 * 1024


def stable_version(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError("Unsupported release version")
    return tuple(map(int, value.removeprefix("v").split(".")))


def release_asset(release: dict) -> dict | None:
    if release.get("draft") or release.get("prerelease"):
        return None
    if stable_version(release["tag_name"]) <= stable_version(VERSION):
        return None
    asset = next((a for a in release["assets"] if a["name"] == "HotsDraft.exe"), None)
    if not asset:
        return None
    prefix = f"https://github.com/{REPO}/releases/download/{release['tag_name']}/"
    if not asset["browser_download_url"].startswith(prefix):
        raise ValueError("Unexpected release asset URL")
    digest = asset.get("digest", "") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Release asset is missing a SHA-256 digest")
    if not 0 < asset["size"] <= MAX_SIZE:
        raise ValueError("Invalid release asset size")
    return asset


def download_update(
    directory: Path, cancelled=lambda: False
) -> tuple[Path, str] | None:
    with httpx.Client(
        follow_redirects=True,
        timeout=15,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"HotsDraft/{VERSION}",
        },
    ) as client:
        response = client.get(LATEST_URL)
        if response.status_code == 404:
            return None  # No published releases yet (or private repository).
        response.raise_for_status()
        release = response.json()
        asset = release_asset(release)
        if not asset or cancelled():
            return None
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"HotsDraft-{release['tag_name']}-{os.getpid()}.exe"
        partial = destination.with_suffix(".partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with (
                client.stream("GET", asset["browser_download_url"]) as stream,
                partial.open("wb") as output,
            ):
                stream.raise_for_status()
                for chunk in stream.iter_bytes():
                    if cancelled():
                        return None
                    size += len(chunk)
                    if size > asset["size"]:
                        raise ValueError("Update exceeds declared size")
                    digest.update(chunk)
                    output.write(chunk)
            if (
                size != asset["size"]
                or digest.hexdigest() != asset["digest"].split(":")[1]
            ):
                raise ValueError("Update checksum or size mismatch")
            with partial.open("rb") as source:
                if source.read(2) != b"MZ":
                    raise ValueError("Update is not a Windows executable")
            os.replace(partial, destination)
            return destination, release["tag_name"]
        finally:
            partial.unlink(missing_ok=True)


def launch_update(
    candidate: Path, target: Path, arguments: list[str], log_dir: Path
) -> None:
    subprocess.Popen(
        [
            str(candidate),
            "--apply-update",
            str(target.resolve()),
            str(os.getpid()),
            json.dumps(arguments),
            str(log_dir.resolve()),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )


def apply_update(
    target: Path, parent_pid: int, arguments: list[str], log_dir: Path
) -> int:
    """Run from the downloaded EXE after the old app exits; retain a backup."""
    import ctypes

    backup = target.with_suffix(".exe.bak")
    install = target.with_suffix(".exe.install")
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle, 30 * 60 * 1000) != 0:
                    raise TimeoutError("Previous app did not exit")
            finally:
                kernel.CloseHandle(handle)
        # The PyInstaller bootstrap process may briefly keep the target locked.
        for attempt in range(120):
            try:
                shutil.copy2(target, backup)
                shutil.copy2(Path(sys.executable), install)
                os.replace(install, target)
                break
            except PermissionError:
                if attempt == 119:
                    raise
                time.sleep(0.5)
        try:
            subprocess.Popen(
                [str(target), "--skip-update-once", *arguments],
                cwd=target.parent,
                close_fds=True,
            )
        except OSError:
            os.replace(backup, target)
            raise
        return 0
    except (OSError, ValueError) as error:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "update-error.log").write_text(str(error), encoding="utf-8")
        install.unlink(missing_ok=True)
        # If replacement failed, restart the existing app rather than strand it.
        subprocess.Popen(
            [str(target), "--skip-update-once", *arguments], close_fds=True
        )
        return 1
