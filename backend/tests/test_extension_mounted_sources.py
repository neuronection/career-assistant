"""The operator feeder's mounted staging wall (ADR-0071 / plan 216).

The stage is a snapshot, never a live read: copy into `.tmp-*`, digest,
initialize the synthetic repository there, rename into the content address.
These tests pin path confinement, symlink/special-file refusal, caps, the
hardlink copy, the `.gitignore` force-add, the production policy gate and the
feeder-scoped local exemption.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.extensions import lifecycle
from app.extensions.lifecycle import LifecycleError, _check_local_root, _stage_mounted_tree


@pytest.fixture
def mount_root(tmp_path, monkeypatch):
    root = tmp_path / "integrations"
    root.mkdir()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "extension_mounted_roots", [str(root)])
    monkeypatch.setattr(settings, "extension_allow_feeder_imports", True)
    monkeypatch.setattr(settings, "app_env", "production")
    return root


def make_bundle(root: Path, name: str = "bundle") -> Path:
    bundle = root / name
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({"id": name}), encoding="utf-8")
    (bundle / "server.py").write_text("print('ok')\n", encoding="utf-8")
    return bundle


def test_stage_snapshots_and_pins(mount_root):
    bundle = make_bundle(mount_root)
    staged, sha, key, resolved = _stage_mounted_tree(bundle)
    assert staged.is_dir() and (staged / ".git").is_dir()
    assert staged.name == lifecycle.digest_tree(staged)
    assert len(sha) == 40
    assert key == staged.parent.name
    assert resolved == bundle.resolve()
    assert (staged / "manifest.json").is_file()

    again, sha2, _, _ = _stage_mounted_tree(bundle)
    assert again == staged, "an unchanged tree reuses its content address"
    assert sha2 == sha, "reuse never appends a commit"


def test_stage_refuses_a_folder_outside_every_root(tmp_path, mount_root):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(outside)
    assert exc.value.code == "path-denied"


def test_stage_requires_the_operator_policy(mount_root, monkeypatch):
    monkeypatch.setattr(settings, "extension_allow_feeder_imports", False)
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(make_bundle(mount_root))
    assert exc.value.code == "path-denied"


def test_stage_refuses_a_symlinked_file(mount_root):
    bundle = make_bundle(mount_root)
    (bundle / "link.txt").symlink_to(bundle / "server.py")
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(bundle)
    assert exc.value.code == "invalid"
    assert "symlink" in exc.value.detail


def test_stage_refuses_a_symlinked_directory(mount_root):
    bundle = make_bundle(mount_root)
    (bundle / "linked-dir").symlink_to(bundle, target_is_directory=True)
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(bundle)
    assert exc.value.code == "invalid"


def test_stage_refuses_a_special_file(mount_root):
    bundle = make_bundle(mount_root)
    os.mkfifo(bundle / "pipe")
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(bundle)
    assert exc.value.code == "invalid"
    assert "non-regular" in exc.value.detail


def test_stage_requires_a_manifest(mount_root):
    bundle = mount_root / "empty"
    bundle.mkdir()
    (bundle / "readme.txt").write_text("no manifest\n", encoding="utf-8")
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(bundle)
    assert exc.value.code == "invalid"
    assert "manifest.json" in exc.value.detail


def test_stage_refuses_a_mount_that_contains_the_staging_store(tmp_path, monkeypatch):
    wide = tmp_path / "wide"
    wide.mkdir()
    monkeypatch.setattr(settings, "data_dir", wide / "data")
    monkeypatch.setattr(settings, "extension_mounted_roots", [str(wide)])
    monkeypatch.setattr(settings, "extension_allow_feeder_imports", True)
    make_bundle(wide)  # manifest one level down — a valid mount on its own
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(wide)
    assert exc.value.code == "invalid"
    assert "must not contain" in exc.value.detail


def test_stage_enforces_the_tree_caps(mount_root, monkeypatch):
    bundle = make_bundle(mount_root)
    monkeypatch.setattr(lifecycle, "TREE_MAX_FILES", 1)
    with pytest.raises(LifecycleError) as exc:
        _stage_mounted_tree(bundle)
    assert exc.value.code == "invalid"
    assert "caps" in exc.value.detail


def test_stage_copies_a_hardlink_and_severs_the_alias(mount_root, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host bytes\n", encoding="utf-8")
    bundle = make_bundle(mount_root)
    os.link(outside, bundle / "linked.txt")

    staged, _, _, _ = _stage_mounted_tree(bundle)
    copied = staged / "linked.txt"
    assert copied.read_text(encoding="utf-8") == "host bytes\n"
    assert copied.stat().st_ino != outside.stat().st_ino, "the copy severs the hardlink"


def test_stage_ignores_a_gitignore_in_the_bundle(mount_root):
    bundle = make_bundle(mount_root)
    (bundle / ".gitignore").write_text("server.py\n", encoding="utf-8")

    staged, _, _, _ = _stage_mounted_tree(bundle)
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=staged, capture_output=True, text=True, check=True
    ).stdout
    assert "server.py" in tracked, "the synthetic commit must not honour a bundle's .gitignore"


def test_stage_leaves_no_trusted_dir_when_pinning_fails(mount_root, monkeypatch):
    bundle = make_bundle(mount_root)

    def boom(_root: Path) -> str:
        raise LifecycleError("not-ready", "git is not installed (simulated)")

    monkeypatch.setattr(lifecycle, "_init_staging_repo", boom)
    with pytest.raises(LifecycleError):
        _stage_mounted_tree(bundle)

    store = Path(settings.data_dir) / lifecycle.IMPORTS_DIRNAME / "mounted"
    assert not any((p / ".git").exists() for p in store.rglob("*") if p.is_dir()), (
        "a failed pin leaves no content address"
    )
    assert list(store.rglob(".tmp-*")) == [], "the temp stage is cleaned up"


def test_local_root_exemption_is_feeder_scoped(mount_root):
    staged, _, _, _ = _stage_mounted_tree(make_bundle(mount_root))
    # A hand-authored local descriptor (no feeder marker) is refused in a
    # production boot, even for a path inside the staging store.
    with pytest.raises(LifecycleError) as exc:
        _check_local_root(str(staged))
    assert exc.value.code == "path-denied"
    # The feeder writers pass feeder=True and are admitted.
    assert _check_local_root(str(staged), feeder=True) == staged
