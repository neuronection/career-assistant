"""Plan 173 — extension display names.

The manifest's root ``title`` rides the managed import into the minted
job source (``job_sources.title``) and refreshes on re-apply; an untitled
manifest falls back to the extension id. The install view and the admin
source view expose it; enabling is unaffected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.extensions import lifecycle
from app.extensions.lifecycle import add_source, install_extension
from app.models.extension_model import ExtensionInstall, ExtensionSource
from app.models.posting_model import JobSource

FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_template_server.py"
FIXTURE_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "mcp_template_manifest.json"
FIXTURE_DOCS = Path(__file__).resolve().parent / "fixtures" / "docs"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(repo.parent),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def _copy_docs(dest: Path) -> None:
    if FIXTURE_DOCS.is_dir():
        shutil.copytree(FIXTURE_DOCS, dest / "docs", dirs_exist_ok=True)


def make_repo(root: Path, manifest: dict, name: str = "title-repo") -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--quiet", "--initial-branch", "main")
    shutil.copyfile(FIXTURE_SERVER, repo / "server.py")
    (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _copy_docs(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", "init")
    return repo


def template_manifest() -> dict:
    return json.loads(FIXTURE_MANIFEST.read_text())


@pytest.fixture
def local_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "extension_local_source_roots", [str(tmp_path)])
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    return tmp_path


@pytest.fixture
def mcp_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "connector_plugins_allowlist", ["mcp"])
    from app.extensions.registry import reset_registry

    reset_registry()
    yield
    reset_registry()


def local_descriptor(repo: Path) -> dict:
    return {
        "local": {"path": str(repo)},
        "ref": {"strategy": "branch", "value": "main"},
    }


async def _add(db, descriptor: dict) -> ExtensionSource:
    view = await add_source(db, descriptor)
    return await db.get(ExtensionSource, uuid.UUID(view["id"]))


async def _echo_for(db, source_id, extension_id="example-posting-fetcher") -> dict:
    preview = await lifecycle.preview_install(db, uuid.UUID(str(source_id)), extension_id)
    return preview["echo"]


async def test_manifest_title_seeds_the_minted_source(
    db, seeded_catalog, local_roots, mcp_allowlist
):
    manifest = template_manifest()
    manifest["title"] = "Example Board"
    repo = make_repo(local_roots, manifest)
    source = await _add(db, local_descriptor(repo))
    view = await install_extension(
        db, source.id, "example-posting-fetcher", consent=await _echo_for(db, source.id)
    )
    row = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.title == "Example Board"
    assert view["title"] == "Example Board"


async def test_untitled_manifest_falls_back_to_the_extension_id(
    db, seeded_catalog, local_roots, mcp_allowlist
):
    manifest = template_manifest()
    manifest.pop("title", None)
    repo = make_repo(local_roots, manifest)
    source = await _add(db, local_descriptor(repo))
    await install_extension(
        db, source.id, "example-posting-fetcher", consent=await _echo_for(db, source.id)
    )
    row = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.title == "example-posting-fetcher"


async def test_reapply_refreshes_the_title_from_the_new_manifest(
    db, seeded_catalog, local_roots, mcp_allowlist
):
    manifest = template_manifest()
    manifest["title"] = "Example Board"
    repo = make_repo(local_roots, manifest)
    source = await _add(db, local_descriptor(repo))
    view = await install_extension(
        db, source.id, "example-posting-fetcher", consent=await _echo_for(db, source.id)
    )
    install = await db.get(ExtensionInstall, uuid.UUID(view["id"]))

    manifest["title"] = "Renamed Board"
    (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", "rename")
    await lifecycle.sync_source(db, source.id)
    await lifecycle.apply_update(db, install.id, consent=await _echo_for(db, source.id))

    row = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.title == "Renamed Board"
