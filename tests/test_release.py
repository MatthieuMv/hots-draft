import sys

import pytest

from hots_draft import release


def test_release_command_versions_and_pushes_exact_branch(monkeypatch, tmp_path):
    source = tmp_path / "src/hots_draft"
    source.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    monkeypatch.setattr(release, "__file__", str(source / "release.py"))
    monkeypatch.setattr(sys, "argv", ["hots-release", "0.2.0"])
    operations = []

    def git(root, *args):
        operations.append(args)
        if args == ("remote", "get-url", "origin"):
            return "git@github.com:MatthieuMv/hots-draft.git"
        if args == ("branch", "--show-current"):
            return "master"
        return ""

    monkeypatch.setattr(release, "git", git)
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: None)
    release.main()
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
    assert (source / "_version.py").read_text() == 'VERSION = "0.2.0"\n'
    assert operations[-1] == ("push", "--atomic", "origin", "master", "v0.2.0")


def test_release_requires_clean_tree_before_any_mutation(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hots-release", "0.2.0"])
    monkeypatch.setattr(release, "git", lambda *args: " M file.py")
    with pytest.raises(SystemExit):
        release.main()


@pytest.mark.parametrize("version", ["0.1.0", "0.0.9", "bad", "1.2.3-beta"])
def test_release_requires_new_stable_version(monkeypatch, version):
    monkeypatch.setattr(sys, "argv", ["hots-release", version])
    with pytest.raises(SystemExit):
        release.main()
