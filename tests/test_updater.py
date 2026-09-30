import hashlib

import httpx
import pytest

from hots_draft import updater


def release(data=b"MZnew executable"):
    return {
        "tag_name": "v9.0.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "NexusDraft.exe",
                "size": len(data),
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "browser_download_url": "https://github.com/MatthieuMv/hots-draft/releases/download/v9.0.0/NexusDraft.exe",
            }
        ],
    }


def mock_client(monkeypatch, payload, data):
    def respond(request):
        return (
            httpx.Response(200, json=payload)
            if request.url == updater.LATEST_URL
            else httpx.Response(200, content=data)
        )

    client = httpx.Client
    monkeypatch.setattr(
        updater.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )


def test_verified_download(monkeypatch, tmp_path):
    mock_client(monkeypatch, release(), b"MZnew executable")
    path, version = updater.download_update(tmp_path)
    assert path.read_bytes() == b"MZnew executable"
    assert version == "v9.0.0"
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("data", [b"MZbad executable", b"bad payload"])
def test_bad_download_never_becomes_executable(monkeypatch, tmp_path, data):
    mock_client(monkeypatch, release(), data)
    with pytest.raises(ValueError):
        updater.download_update(tmp_path)
    assert not list(tmp_path.iterdir())


def test_release_selection_rejects_missing_digest_external_url_and_older_version():
    payload = release()
    payload["tag_name"] = "v0.0.1"
    assert updater.release_asset(payload) is None
    payload = release()
    payload["prerelease"] = True
    assert updater.release_asset(payload) is None
    for key, value in [
        ("digest", None),
        ("browser_download_url", "https://evil.test/app.exe"),
        ("size", updater.MAX_SIZE + 1),
    ]:
        payload = release()
        payload["assets"][0][key] = value
        with pytest.raises(ValueError):
            updater.release_asset(payload)


def test_cancel_does_not_download(monkeypatch, tmp_path):
    mock_client(monkeypatch, release(), b"MZnew executable")
    assert updater.download_update(tmp_path, lambda: True) is None
    assert not list(tmp_path.iterdir())


def test_replacement_keeps_backup_and_restarts_with_arguments(monkeypatch, tmp_path):
    import ctypes

    class Function:
        def __call__(self, *args):
            return 0

    class Kernel:
        OpenProcess = Function()
        WaitForSingleObject = Function()
        CloseHandle = Function()

    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *args, **kwargs: Kernel(), raising=False
    )
    target = tmp_path / "NexusDraft.exe"
    target.write_bytes(b"MZold")
    candidate = tmp_path / "new.exe"
    candidate.write_bytes(b"MZnew")
    monkeypatch.setattr(updater.sys, "executable", str(candidate))
    starts = []
    monkeypatch.setattr(
        updater.subprocess, "Popen", lambda args, **kwargs: starts.append(args)
    )
    assert (
        updater.apply_update(target, 0, ["--data-dir", "folder with spaces"], tmp_path)
        == 0
    )
    assert target.read_bytes() == b"MZnew"
    assert target.with_suffix(".exe.bak").read_bytes() == b"MZold"
    assert starts[0] == [
        str(target),
        "--skip-update-once",
        "--data-dir",
        "folder with spaces",
    ]


def test_release_versions_are_numeric():
    assert updater.stable_version("v1.10.0") > updater.stable_version("1.9.9")
    with pytest.raises(ValueError):
        updater.stable_version("../../app")


def test_no_releases_leaves_app_untouched(monkeypatch, tmp_path):
    client = httpx.Client
    monkeypatch.setattr(
        updater.httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404)), **kwargs
        ),
    )
    assert updater.download_update(tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_restart_failure_restores_previous_executable(monkeypatch, tmp_path):
    import ctypes

    class Function:
        def __call__(self, *args):
            return 0

    class Kernel:
        OpenProcess = Function()
        WaitForSingleObject = Function()
        CloseHandle = Function()

    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *args, **kwargs: Kernel(), raising=False
    )
    target = tmp_path / "NexusDraft.exe"
    target.write_bytes(b"MZold")
    candidate = tmp_path / "new.exe"
    candidate.write_bytes(b"MZnew")
    monkeypatch.setattr(updater.sys, "executable", str(candidate))
    starts = []

    def start(args, **kwargs):
        starts.append(args)
        if len(starts) == 1:
            raise OSError("Launch failed")

    monkeypatch.setattr(updater.subprocess, "Popen", start)
    assert updater.apply_update(target, 0, [], tmp_path) == 1
    assert target.read_bytes() == b"MZold"
    assert (tmp_path / "update-error.log").read_text() == "Launch failed"
    assert len(starts) == 2
