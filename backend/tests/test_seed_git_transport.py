"""Plan 218: public git transport (local fixture repo, never a live host)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import sha256_hex
from app.services.seeds.git_transport import (
    GitTransport,
    validate_public_git_uri,
    validate_subpath,
)

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_pack(root: Path, name: str) -> None:
    items = root / "pack"
    (items / "items/ats_presets").mkdir(parents=True, exist_ok=True)
    envelope = {
        "metadata": {
            "item_type": "ats_presets",
            "format": "ats_presets",
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
            "license": "CC-BY-4.0",
        },
        "items": [
            {
                "seed_key": "ats-preset:acme",
                "slug": "acme",
                "name": name,
                "connector_key": "recruitee",
                "platform": "Recruitee",
                "category": "ats",
                "country": "GR",
                "config": {"company": "acme"},
            }
        ],
    }
    data = json.dumps(envelope, sort_keys=True).encode()
    (items / "items/ats_presets/acme.json").write_bytes(data)
    manifest = {
        "id": "test-pack",
        "schema_version": "1.0",
        "version": "1.0.0",
        "license": "CC-BY-4.0",
        "scope": "system",
        "priority": 100,
        "item_files": [{"path": "items/ats_presets/acme.json", "sha256": sha256_hex(data)}],
    }
    (items / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    _write_pack(repo, "Acme v1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "tag", "v1")
    _write_pack(repo, "Acme v2")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v2")
    return repo


def test_public_uri_validation():
    assert validate_public_git_uri("https://github.com/neuronection/career-assistant-seeds.git")
    for uri in (
        "http://github.com/x/y.git",
        "file:///tmp/repo",
        "https://user:pass@github.com/x/y.git",
        "https://github.com/x/y.git?ref=main",
        "https://localhost/x/y.git",
        "https://127.0.0.1/x/y.git",
        "https://10.0.0.1/x/y.git",
    ):
        with pytest.raises(SeedPackError):
            validate_public_git_uri(uri)


def test_subpath_validation():
    assert validate_subpath("packs/neuronection/greece-ats") == "packs/neuronection/greece-ats"
    assert validate_subpath("") == ""
    for value in ("../x", "/abs", "packs/../x", "a\\b"):
        with pytest.raises(SeedPackError):
            validate_subpath(value)


async def test_fetch_pins_the_requested_tag(tmp_path):
    repo = _repo(tmp_path)
    pack = await GitTransport(allow_local=True).fetch(str(repo), "v1", "pack")
    assert pack.commit_sha
    assert pack.commit_sha != _git(repo, "rev-parse", "HEAD")
    item = json.loads(pack.files["items/ats_presets/acme.json"])
    assert item["items"][0]["name"] == "Acme v1"
    assert "manifest.json" in pack.files


async def test_git_unavailable_is_typed(monkeypatch):
    import app.services.seeds.git_transport as git_module

    monkeypatch.setattr(git_module, "git_available", lambda: False)
    with pytest.raises(SeedPackError) as exc:
        await GitTransport().fetch("https://github.com/example/seeds.git", "v1", "")
    assert exc.value.code == "GIT_UNAVAILABLE"


async def test_fetch_without_local_opt_in_rejects_a_path(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(SeedPackError) as exc:
        await GitTransport().fetch(str(repo), "v1", "pack")
    assert exc.value.code == "GIT_URI_DENIED"


async def test_discover_reads_the_root_index(tmp_path):
    repo = _repo(tmp_path)
    index = {
        "schemaVersion": 1,
        "kind": "career-seed-repo",
        "publisher": {"id": "test", "name": "Test"},
        "packs": [
            {
                "id": "test-pack",
                "path": "pack",
                "manifest": "pack/manifest.json",
                "itemTypes": ["ats_presets"],
                "license": "CC-BY-4.0",
                "version": "1.0.0",
                "digest": f"sha256:{'a' * 64}",
                "signature": None,
            }
        ],
    }
    (repo / "seed-repo.json").write_text(json.dumps(index), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "index")
    _git(repo, "tag", "v2")

    raw, commit = await GitTransport(allow_local=True).discover(str(repo), "v2")
    assert json.loads(raw)["packs"][0]["id"] == "test-pack"
    assert commit
