"""The extension import layer wall (plan 32 Phase 3 / ADR-0040 D13+D15+D22).

Covers the whole pipeline against REAL local git repos (``git init`` in
tmp dirs — no external network) plus the sibling template repo when the
family dev layout is checked out:

* e2e: add a ``local`` source → sync → discovered candidate → consent
  install → the minted MCP job source spawns ``server.py`` FROM THE
  CLONED CONTENT → ``sync_source`` lands postings with attribution, the
  etag cursor short-circuits the second sync, tool calls audited;
* consent: no install without consent; the consent record persists
  who/when/what-digest and carries the T3 perimeter disclosure VERBATIM
  from the vendored charter;
* adversarial sources (the plan's required list): bad schema rejected
  typed; wrong host profile (kind/tier not hosted) rejected with reason;
  apiVersion too new rejected; digest drift on a pinned ref = LOUD
  failure, pins untouched, never a silent refetch; capability growth on
  update requires re-consent (blocked until then); malformed repo (no
  manifests) typed error; path traversal in a local source root denied;
  inline token in a descriptor structurally rejected (schema seam);
* local gating: production boots reject local sources fail-closed;
  non-allowlisted roots rejected (net_guard-style confinement);
* GitOps conflict cases: manual installs never re-pinned (drift
  reported); failed fetch leaves pins untouched + source failing; pin
  moves apply; removal from the list parks disabled + data intact +
  tombstone-able; reconcile NEVER enables anything;
* private repo: a descriptor carrying a credential slot reference, the
  sealed value resolving host-side into the git env (GIT_CONFIG_*),
  nothing leaking into logs or stored echoes.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.extensions import lifecycle
from app.extensions.lifecycle import (
    GitTransport,
    LifecycleError,
    add_source,
    apply_update,
    get_desired_state,
    install_extension,
    list_sources,
    put_desired_state,
    reconcile,
    set_git_transport,
    sync_source,
    validate_source_descriptor,
)
from app.extensions.registry import reset_registry
from app.models.extension_model import ExtensionInstall, ExtensionSource
from app.models.posting_model import JobSource

TEMPLATE_DIR = Path(__file__).resolve().parents[2].parent / "career-connector-template"
FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_template_server.py"
FIXTURE_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "mcp_template_manifest.json"

BOARD_ROW_IDS = ("default-1", "default-2", "default-3")


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


def make_repo(
    root: Path,
    name: str = "ext-repo",
    *,
    manifest: dict | None = None,
    tag: str | None = "v1.0.0",
    subpath: str = "",
) -> Path:
    """A real local git repo: manifest.json (+ subpath variant) + the
    template server as the runnable entry."""
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--quiet", "--initial-branch", "main")
    entry_dir = repo / subpath if subpath else repo
    entry_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_SERVER, entry_dir / "server.py")
    manifest = manifest if manifest is not None else json.loads(FIXTURE_MANIFEST.read_text())
    (entry_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", "init")
    if tag:
        _git(repo, "tag", tag)
    return repo


def template_manifest() -> dict:
    return json.loads(FIXTURE_MANIFEST.read_text())


@pytest.fixture
def local_roots(tmp_path, monkeypatch):
    """Allowlisted local roots + dev env — the local kind's confinement."""
    monkeypatch.setattr(settings, "extension_local_source_roots", [str(tmp_path)])
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    return tmp_path


@pytest.fixture
def mcp_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "connector_plugins_allowlist", ["mcp"])
    reset_registry()
    yield
    reset_registry()


def local_descriptor(repo: Path, **ref) -> dict:
    return {
        "local": {"path": str(repo)},
        "ref": {"strategy": "branch", "value": "main", **ref},
    }


async def _actor_id(db) -> uuid.UUID:
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    if user is None:
        user = User(email="ext-admin@example.com", full_name="Ext Admin", is_admin=True)
        db.add(user)
        await db.commit()
    return user.id


async def _add(db, descriptor: dict, **kw) -> ExtensionSource:
    view = await add_source(db, descriptor, **kw)
    return await db.get(ExtensionSource, uuid.UUID(view["id"]))


# ------------------------------------------------------------- e2e import


async def test_e2e_import_from_a_local_git_repo(db, seeded_catalog, local_roots, mcp_allowlist):
    """The Phase-3 wall: source → consent → installed MCP connector
    instance → managed-spawn server.py from the CLONED content → postings
    land with attribution; the etag short-circuits sync two; audit rows
    exist for every tool call."""
    from app.services.postings_service import sync_source as sync_job_source

    repo = make_repo(local_roots)
    source = await _add(db, local_descriptor(repo))

    report = await sync_source(db, source.id)
    assert report["ok"] is True, report
    [candidate] = report["candidates"]
    assert candidate["extensionId"] == "example-posting-fetcher"
    assert candidate["compatible"] is True
    assert candidate["hasEntry"] is True

    installed = await install_extension(
        db, source.id, "example-posting-fetcher", consent=True, actor_id=await _actor_id(db)
    )
    assert installed["originClass"] == "imported"
    assert installed["enabled"] is False, "installs are disabled — enable is an explicit act"

    rows = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    minted = rows[0]
    assert minted.connector_key == "mcp"
    assert minted.enabled is False
    content_dir = Path(installed["contentPath"])
    assert content_dir.is_dir()
    assert (content_dir / "server.py").is_file()
    assert str(content_dir).startswith(str(settings.data_dir / "extensions"))
    assert str(content_dir.parent.name) == "example-posting-fetcher"
    assert content_dir.name == installed["digest"], "content-addressed by digest"
    assert str(content_dir / "server.py") in minted.config["command"]

    enabled = await lifecycle.set_install_enabled(db, uuid.UUID(installed["id"]), True)
    assert enabled["enabled"] is True
    await db.refresh(minted)
    assert minted.enabled is True

    first = await sync_job_source(db, minted)
    assert first["errors"] == [], first
    assert first["synced"] == 3
    from app.models.posting_model import JobPosting

    postings = (
        (
            await db.execute(
                select(JobPosting)
                .where(JobPosting.source_id == minted.id)
                .order_by(JobPosting.external_id)
            )
        )
        .scalars()
        .all()
    )
    assert [p.external_id for p in postings] == list(BOARD_ROW_IDS)
    for posting in postings:
        assert posting.source_id == minted.id
        assert posting.org == "Reference Systems"
        assert posting.url.startswith("https://jobs.example.com/")
    assert minted.sync_state.get("etag"), "the tool's cursor round-trips"

    second = await sync_job_source(db, minted)
    assert second["synced"] == 0, "the etag cursor short-circuits the second sync"

    from app.models.ai_model import AIGeneration
    from app.models.enums import AITaskType

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 2, "one audit row per tool call"


# ---------------------------------------------------------------- consent


async def test_consent_is_required_and_records_persist_verbatim(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots)
    source = await _add(db, local_descriptor(repo))
    await sync_source(db, source.id)

    with pytest.raises(LifecycleError) as no_consent:
        await install_extension(db, source.id, "example-posting-fetcher", consent=False)
    assert "consent is required" in no_consent.value.detail

    view = await install_extension(
        db, source.id, "example-posting-fetcher", consent=True, actor_id=await _actor_id(db)
    )
    install = await db.get(ExtensionInstall, uuid.UUID(view["id"]))
    [record] = install.consents
    assert record["digest"] == install.digest
    assert record["actor"]
    assert record["at"]
    assert record["tier"] == "T3"
    assert record["provenance"]["author"] == "Neuronection"
    assert record["provenance"]["license"] == "MIT"
    charter = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "extension-charter.json").read_text()
    )
    assert record["disclosure"] == charter["consent"]["t3PerimeterDisclosure"], (
        "the T3 perimeter copy renders VERBATIM from the charter (D22)"
    )


async def test_tombstone_retains_consent_and_never_reenables(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots)
    source = await _add(db, local_descriptor(repo))
    await sync_source(db, source.id)
    view = await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    await lifecycle.set_install_enabled(db, uuid.UUID(view["id"]), True)

    tombstoned = await lifecycle.tombstone_install(db, uuid.UUID(view["id"]))
    assert tombstoned["state"] == "removed"
    install = await db.get(ExtensionInstall, uuid.UUID(view["id"]))
    assert install.consents, "consent records survive tombstoning"
    assert install.tombstoned_at is not None
    rows = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .all()
    )
    assert rows[0].enabled is False

    with pytest.raises(LifecycleError) as exc:
        await lifecycle.set_install_enabled(db, uuid.UUID(view["id"]), True)
    assert "never re-enabled" in exc.value.detail


# ------------------------------------------------------- adversarial sources


async def test_bad_manifest_schema_is_rejected_typed(db, local_roots):
    manifest = template_manifest()
    del manifest["author"]
    del manifest["i18n"]
    repo = make_repo(local_roots, manifest=manifest)
    source = await _add(db, local_descriptor(repo))
    report = await sync_source(db, source.id)
    assert report["ok"] is False
    assert report["error"]["code"] == "invalid"
    assert "manifest invalid" in report["error"]["detail"]


async def test_wrong_host_profile_rejected_with_reason(db, local_roots):
    for kind in ("mini-app", "bridge"):
        manifest = template_manifest()
        manifest["kind"] = kind
        if kind == "mini-app":
            manifest["packKind"] = "surface"
            manifest["apiVersion"] = 1
            manifest.pop("kindVersion", None)
            manifest.pop("itemSchema", None)
            manifest.pop("supportsIncremental", None)
        repo = make_repo(local_roots, name=f"repo-{kind}", manifest=manifest, tag=None)
        source = await _add(db, local_descriptor(repo))
        report = await sync_source(db, source.id)
        if report["ok"] and report["candidates"]:
            candidate = report["candidates"][0]
            assert candidate["compatible"] is False
            # Since plan-32 Phase 4 the mini-app kind IS hosted: this
            # modified shape (no ui:* surface declared, connector caps) is
            # still rejected typed — the precise capability/surface reason
            # says which (D17: the compatibility check is data). bridge
            # stays kind-named.
            if kind == "bridge":
                assert kind in candidate["reason"]
            else:
                assert candidate.get("reason"), "a typed reason is the law (D17)"


async def test_api_version_too_new_rejected_with_ceiling(db, local_roots):
    manifest = template_manifest()
    manifest["kindVersion"] = 2
    repo = make_repo(local_roots, manifest=manifest)
    source = await _add(db, local_descriptor(repo))
    report = await sync_source(db, source.id)
    assert report["ok"] is False
    assert report["error"]["code"] == "invalid"
    assert "kindVersion" in report["error"]["detail"], "the error names the ceiling precisely"


async def test_unhonored_capability_rejected(db, local_roots):
    manifest = template_manifest()
    manifest["capabilities"] = ["sync", "net"]
    manifest["domains"] = ["example.com"]
    repo = make_repo(local_roots, manifest=manifest)
    source = await _add(db, local_descriptor(repo))
    report = await sync_source(db, source.id)
    assert report["ok"] is True
    [candidate] = report["candidates"]
    assert candidate["compatible"] is False
    assert "net" in candidate["reason"], "T3 imports grant no host-side net"


async def test_malformed_repo_no_manifests_typed_error(db, local_roots):
    repo = make_repo(local_roots, tag=None)
    (repo / "manifest.json").unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "drop manifest")
    source = await _add(db, local_descriptor(repo))
    report = await sync_source(db, source.id)
    assert report["ok"] is False
    assert report["error"]["code"] == "invalid"
    assert "no extension manifests" in report["error"]["detail"]
    assert source.status == "failing"


async def test_missing_entry_file_rejected_at_install(db, local_roots):
    repo = make_repo(local_roots, tag=None)
    (repo / "server.py").unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "drop entry")
    source = await _add(db, local_descriptor(repo))
    await sync_source(db, source.id)
    with pytest.raises(LifecycleError) as exc:
        await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    assert exc.value.code == "unsupported"
    assert "server.py" in exc.value.detail


async def test_digest_drift_on_pinned_ref_is_a_loud_failure(db, local_roots, mcp_allowlist):
    """Tag force-move under the SAME tag name: the recorded digest no
    longer matches — loud, blocking, pins untouched, never a refetch."""
    repo = make_repo(local_roots, tag="v1.0.0")
    descriptor = local_descriptor(repo, strategy="release-tag")
    source = await _add(db, descriptor)
    await sync_source(db, source.id)
    view = await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    pinned_digest = view["digest"]

    (repo / "manifest.json").write_text(
        json.dumps({**template_manifest(), "version": "1.0.1"}), encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "rewrite")
    _git(repo, "tag", "--force", "v1.0.0")

    report = await sync_source(db, source.id)
    assert report["ok"] is True
    install = await db.get(ExtensionInstall, uuid.UUID(view["id"]))
    assert install.update["state"] == "digest-drift"
    assert install.digest == pinned_digest, "the pin is untouched — no silent refetch"
    assert install.update["expectedDigest"] == pinned_digest
    assert source.status == "degraded"

    with pytest.raises(LifecycleError) as exc:
        await apply_update(db, install.id, consent=True)
    assert "no update available" in exc.value.detail


async def test_capability_growth_requires_reconsent(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots, tag="v1.0.0")
    descriptor = local_descriptor(repo, strategy="release-tag")
    source = await _add(db, descriptor)
    await sync_source(db, source.id)
    view = await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    install_id = uuid.UUID(view["id"])

    manifest = template_manifest()
    manifest["version"] = "1.1.0"
    manifest["capabilities"] = ["sync", "secrets"]
    (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "grow capabilities")
    _git(repo, "tag", "v1.1.0")

    await sync_source(db, source.id)
    install = await db.get(ExtensionInstall, install_id)
    assert install.update["state"] == "available"
    assert install.update["requiresReconsent"] is True, "capability growth re-consents (D15)"
    assert install.update["manifestDiff"]["capabilitiesAdded"] == ["secrets"]
    assert install.digest == view["digest"], "nothing applied without the explicit act"

    with pytest.raises(LifecycleError) as no_apply:
        await apply_update(db, install_id, consent=False)
    assert "re-consent" in no_apply.value.detail
    reapplied = await apply_update(db, install_id, consent=True)
    assert reapplied["digest"] != view["digest"], "the re-consent applies the new pin"
    install = await db.get(ExtensionInstall, install_id)
    assert install.update == {}
    assert [c for c in install.consents if c.get("reconsent")], "the re-consent is recorded"


async def test_benign_ref_move_applies_without_reconsent(db, local_roots, mcp_allowlist):
    """A ref that moved with IDENTICAL content is a pin move, not an
    update — nothing consented changed."""
    repo = make_repo(local_roots, tag="v1.0.0")
    descriptor = local_descriptor(repo, strategy="release-tag")
    source = await _add(db, descriptor)
    await sync_source(db, source.id)
    view = await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    install_id = uuid.UUID(view["id"])

    _git(repo, "tag", "v1.0.1")

    await sync_source(db, source.id)
    install = await db.get(ExtensionInstall, install_id)
    assert install.update == {}
    assert install.digest == view["digest"]
    assert install.pin_ref == "v1.0.1", "the identical-content ref move applied"
    assert len(install.pin_history) == 2


# --------------------------------------------------------- local gating


async def test_local_sources_fail_closed_in_production(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "extension_local_source_roots", [str(tmp_path)])
    with pytest.raises(LifecycleError) as exc:
        validate_source_descriptor(
            {"local": {"path": str(tmp_path)}, "ref": {"strategy": "branch", "value": "main"}}
        )
    assert exc.value.code == "path-denied"
    assert "production" in exc.value.detail


async def test_local_roots_confine_no_arbitrary_traversal(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "extension_local_source_roots", [str(tmp_path / "allowed")])
    repo = make_repo(tmp_path, name="outside")
    with pytest.raises(LifecycleError) as exc:
        validate_source_descriptor(local_descriptor(repo))
    assert exc.value.code == "path-denied"
    assert "outside every allowlisted root" in exc.value.detail

    with pytest.raises(LifecycleError) as rel:
        validate_source_descriptor(
            {"local": {"path": "../etc"}, "ref": {"strategy": "branch", "value": "main"}}
        )
    assert rel.value.code == "invalid", "relative/traversal paths die at the schema seam"


async def test_descriptor_with_inline_token_structurally_rejected(db, tmp_path):
    from app.extensions import contract

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "contracts" / "extension-sources.schema.json"
        ).read_text()
    )
    userinfo = {
        "url": "https://user:ghp_token123@git.example.com/ext/repo",
        "ref": {"strategy": "release-tag"},
    }
    assert contract.validate(schema, userinfo, schema) is not None
    smuggled = {
        "url": "https://git.example.com/ext/repo",
        "ref": {"strategy": "release-tag"},
        "credentials": [{"slot": "ok-slot", "value": "ghp_token123"}],
    }
    assert contract.validate(schema, smuggled, schema) is not None


# ------------------------------------------------------------- GitOps


async def _gitops_doc(repo: Path, *, digest: str, ref: str = "v1.0.0") -> dict:
    return {
        "schema": 1,
        "sources": [
            {
                "url": "https://git.example.com/example/ext-repo",
                "ref": {"strategy": "release-tag"},
            }
        ],
        "extensions": [
            {
                "id": "example-posting-fetcher",
                "sourceUrl": "https://git.example.com/example/ext-repo",
                "pin": {"ref": ref, "digest": digest},
                "enabled": True,
            }
        ],
    }


class FakeHttpsTransport(GitTransport):
    """An https git transport seam: serves a local repo's objects behind a
    required Bearer header — the private-repo fixture (no network)."""

    def __init__(self, repo: Path, *, expect_token: str | None = None):
        self.repo = repo
        self.expect_token = expect_token
        self.saw_header = False
        self.env_seen: dict | None = None

    async def resolve(self, origin: str, ref: dict, *, token: str | None = None):
        if self.expect_token is not None:
            if token != self.expect_token:
                raise LifecycleError("auth", "https transport: missing/invalid bearer token")
            self.saw_header = True
        return await super().resolve(str(self.repo), ref)

    async def fetch(self, origin, resolved, dest, *, token: str | None = None):
        await super().fetch(str(self.repo), resolved, dest)


async def test_gitops_pin_move_applies_and_never_enables(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots, tag="v1.0.0")
    fake = FakeHttpsTransport(repo)
    set_git_transport(fake)
    try:
        digest = lifecycle.digest_tree(repo)
        await put_desired_state(db, await _gitops_doc(repo, digest=digest, ref="v1.0.0"))
        report = await reconcile(db)
        assert report["needsConsent"] and not report["installed"], (
            "consent is the gate — the list is only a pin-mover (D13)"
        )
        assert report["ignoredEnableIntent"], "reconcile never auto-enables (D22)"

        source = (await db.execute(select(ExtensionSource))).scalars().first()
        await sync_source(db, source.id)
        await install_extension(
            db, source.id, "example-posting-fetcher", consent=True, managed_by="gitops"
        )
        rows = (
            (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
            .scalars()
            .all()
        )
        assert rows[0].enabled is False, "reconcile never enables anything"

        _git(repo, "tag", "v1.0.1")
        await put_desired_state(db, await _gitops_doc(repo, digest=digest, ref="v1.0.1"))
        report = await reconcile(db)
        assert report["pinsMoved"], "the identical-content pin move applies"
        install = (
            (
                await db.execute(
                    select(ExtensionInstall).where(
                        ExtensionInstall.extension_id == "example-posting-fetcher"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert install.pin_ref == "v1.0.1"
        assert install.digest == digest
        await db.refresh(rows[0])
        assert rows[0].enabled is False, "still never enabled"
    finally:
        set_git_transport(None)


async def test_gitops_removal_from_list_parks_data_intact(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots, tag="v1.0.0")
    digest = lifecycle.digest_tree(repo)
    await put_desired_state(db, await _gitops_doc(repo, digest=digest))
    set_git_transport(FakeHttpsTransport(repo))
    try:
        source = await _add(
            db,
            {
                "url": "https://git.example.com/example/ext-repo",
                "ref": {"strategy": "release-tag"},
            },
        )
        await sync_source(db, source.id)
        view = await install_extension(
            db, source.id, "example-posting-fetcher", consent=True, managed_by="gitops"
        )
        install_id = uuid.UUID(view["id"])
        await lifecycle.set_install_enabled(db, install_id, True)

        await put_desired_state(db, {"schema": 1, "sources": [], "extensions": []})
        report = await reconcile(db)
        assert any(entry["extensionId"] == "example-posting-fetcher" for entry in report["parked"])
        install = await db.get(ExtensionInstall, install_id)
        assert install.parked is True
        assert install.state == "disabled"
        assert install.enabled is False
        assert install.consents, "data + consent records intact"
        assert Path(install.content_path).is_dir(), "content never deleted"

        tombstoned = await lifecycle.tombstone_install(db, install_id)
        assert tombstoned["state"] == "removed"
    finally:
        set_git_transport(None)


async def test_gitops_never_repins_manual_installs(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots, tag="v1.0.0")
    url = "https://git.example.com/example/ext-repo"
    set_git_transport(FakeHttpsTransport(repo))
    try:
        source = await _add(db, {"url": url, "ref": {"strategy": "release-tag"}})
        await sync_source(db, source.id)
        view = await install_extension(
            db, source.id, "example-posting-fetcher", consent=True, managed_by="manual"
        )
        install_id = uuid.UUID(view["id"])

        doc = await _gitops_doc(repo, digest="9" * 64, ref="v0.9.9-fake")
        await put_desired_state(db, doc)
        report = await reconcile(db)
        assert any(
            entry["extensionId"] == "example-posting-fetcher" and "manual" in entry["reason"]
            for entry in report["drift"]
        ), "drift vs manual installs is REPORTED, never reverted"
        install = await db.get(ExtensionInstall, install_id)
        assert install.pin_ref == view["pinRef"]
        assert install.managed_by == "manual"
        assert install.digest == view["digest"]
    finally:
        set_git_transport(None)


async def test_gitops_failed_fetch_leaves_pins_untouched(db, local_roots, mcp_allowlist):
    repo = make_repo(local_roots, tag="v1.0.0")
    source = await _add(db, local_descriptor(repo))
    await sync_source(db, source.id)
    view = await install_extension(db, source.id, "example-posting-fetcher", consent=True)
    install_id = uuid.UUID(view["id"])

    class BrokenTransport(GitTransport):
        async def resolve(self, origin, ref, *, token=None):
            raise LifecycleError("unreachable", "the remote is down (simulated)")

    set_git_transport(BrokenTransport())
    try:
        report = await sync_source(db, source.id)
        assert report["ok"] is False
        assert report["error"]["code"] == "unreachable"
        install = await db.get(ExtensionInstall, install_id)
        assert install.digest == view["digest"], "pins untouched"
        assert install.pin_ref == view["pinRef"]
        await db.refresh(source)
        assert source.status == "failing"
        assert source.consecutive_failures == 1
        assert install.update.get("lastCheckFailed") is True
    finally:
        set_git_transport(None)


async def test_gitops_never_auto_applies_code_updates(db, local_roots, mcp_allowlist):
    """A digest change named by the desired list is still only an
    update-offer: without a prior consent at that digest, nothing lands."""
    repo = make_repo(local_roots, tag="v1.0.0")
    set_git_transport(FakeHttpsTransport(repo))
    try:
        source = await _add(
            db,
            {
                "url": "https://git.example.com/example/ext-repo",
                "ref": {"strategy": "release-tag"},
            },
        )
        await sync_source(db, source.id)
        view = await install_extension(
            db, source.id, "example-posting-fetcher", consent=True, managed_by="gitops"
        )

        manifest = template_manifest()
        manifest["version"] = "2.0.0"
        (repo / "server.py").write_text(
            (repo / "server.py").read_text() + "\n# changed\n", encoding="utf-8"
        )
        (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "--quiet", "-m", "code change")
        _git(repo, "tag", "v2.0.0")
        new_digest = lifecycle.digest_tree(repo)

        doc = await _gitops_doc(repo, digest=new_digest, ref="v2.0.0")
        await put_desired_state(db, doc)
        report = await reconcile(db)
        assert any(entry.get("requiresReconsent") for entry in report["updatesAvailable"]), (
            "code updates never auto-apply (D22)"
        )
        install = (
            (
                await db.execute(
                    select(ExtensionInstall).where(
                        ExtensionInstall.extension_id == "example-posting-fetcher"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert install.digest == view["digest"], "the pin did NOT move"
    finally:
        set_git_transport(None)


# -------------------------------------------------------- private repos


async def test_private_repo_secret_slot_resolves_and_never_leaks(
    db, local_roots, mcp_allowlist, caplog
):
    """The descriptor references a credential SLOT; the sealed value
    resolves host-side into the git environment — the transport sees the
    header, logs and stored echoes never see the token."""
    from app.core.encryption import decrypt_secret

    repo = make_repo(local_roots, tag="v1.0.0")
    token = "ghp_supersecret_private_repo_token"
    fake = FakeHttpsTransport(repo, expect_token=token)
    set_git_transport(fake)
    caplog.set_level(logging.DEBUG)
    try:
        source = await _add(
            db,
            {
                "url": "https://git.example.com/example/private-ext",
                "ref": {"strategy": "release-tag"},
                "credentials": [{"slot": "repo-token", "purpose": "private repo read"}],
            },
            secrets={"repo-token": token},
        )
        sealed = source.secrets["repo-token"]
        assert sealed.startswith("enc::"), "the slot value is atrest-sealed"
        assert decrypt_secret(sealed) == token
        assert token not in json.dumps(source.descriptor), "never in the descriptor"

        report = await sync_source(db, source.id)
        assert report["ok"] is True
        assert fake.saw_header is True, "the sealed value reached the git env"

        views = await list_sources(db)
        dumped = json.dumps(views)
        assert token not in dumped
        assert "repo-token" in dumped, "slot presence IS surfaced"
    finally:
        set_git_transport(None)
    assert token not in caplog.text, "nothing leaks into logs"


# ------------------------------------------------------- desired state law


async def test_desired_state_rejects_deletion_structurally(db):
    doc = {
        "schema": 1,
        "sources": [],
        "extensions": [
            {
                "id": "example-posting-fetcher",
                "sourceUrl": "https://git.example.com/x",
                "pin": {"ref": "v1", "digest": "9" * 64},
                "remove": True,
            }
        ],
    }
    with pytest.raises(LifecycleError) as exc:
        await put_desired_state(db, doc)
    assert "remove" in exc.value.detail


async def test_reconcile_without_desired_state_is_a_noop(db):
    assert await get_desired_state(db) == {}
    report = await reconcile(db)
    assert report == {key: [] for key in report}


# ------------------------------------------------------ the admin API path


async def test_sources_ride_the_admin_api_surface(
    db, client, auth_headers, local_roots, mcp_allowlist
):
    """The settings-UI surface: add → sync → consent install (400 without
    consent) → enable → desired-state PUT validated → secret-safe list."""
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    repo = make_repo(local_roots)
    created = await client.post(
        "/api/v1/admin/extensions/sources",
        json={"descriptor": local_descriptor(repo)},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    listed = await client.get("/api/v1/admin/extensions/sources", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["origin"] == str(repo)
    assert listed.json()[0]["kind"] == "local"

    synced = await client.post(
        f"/api/v1/admin/extensions/sources/{source_id}/sync", headers=auth_headers
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["ok"] is True

    denied = await client.post(
        f"/api/v1/admin/extensions/sources/{source_id}/install",
        json={"extension_id": "example-posting-fetcher", "consent": False},
        headers=auth_headers,
    )
    assert denied.status_code == 400
    assert "consent" in denied.json()["detail"]

    installed = await client.post(
        f"/api/v1/admin/extensions/sources/{source_id}/install",
        json={"extension_id": "example-posting-fetcher", "consent": True},
        headers=auth_headers,
    )
    assert installed.status_code == 201, installed.text
    assert installed.json()["enabled"] is False
    install_id = installed.json()["id"]

    enabled = await client.post(
        f"/api/v1/admin/extensions/installs/{install_id}/enabled",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    bad_doc = await client.put(
        "/api/v1/admin/extensions/desired-state",
        json={"schema": 1, "sources": [], "extensions": [{"id": "x"}]},
        headers=auth_headers,
    )
    assert bad_doc.status_code == 400

    doc = await client.put(
        "/api/v1/admin/extensions/desired-state",
        json={"schema": 1, "sources": [], "extensions": []},
        headers=auth_headers,
    )
    assert doc.status_code == 200
    got = await client.get("/api/v1/admin/extensions/desired-state", headers=auth_headers)
    assert got.json() == {"schema": 1, "sources": [], "extensions": []}


# ------------------------------------------------- template-repo fidelity


def test_fixture_manifest_matches_the_canonical_template():
    canonical = TEMPLATE_DIR / "manifest.json"
    if not canonical.exists():
        pytest.skip(f"sibling template repo not checked out: {TEMPLATE_DIR}")
    assert FIXTURE_MANIFEST.read_bytes() == canonical.read_bytes(), (
        "fixtures/mcp_template_manifest.json drifted from career-connector-template/manifest.json"
    )


def _template_roots() -> list[Path]:
    """The CI-safe fixture files always build the repo; the canonical
    sibling checkout joins when the family dev layout exists."""
    roots = [Path(__file__).resolve().parent / "fixtures"]
    if (TEMPLATE_DIR / "manifest.json").exists():
        roots.append(TEMPLATE_DIR)
    return roots


@pytest.fixture(params=_template_roots(), ids=lambda p: p.name)
def template_repo(local_roots, request) -> Path:
    """A real git repo built from the template's manifest+server — either
    the byte-identical fixture copies or the canonical sibling checkout."""
    origin = request.param
    names = (
        {"manifest.json": "manifest.json", "server.py": "server.py"}
        if (origin / "manifest.json").exists()
        else {"manifest.json": "mcp_template_manifest.json", "server.py": "mcp_template_server.py"}
    )
    repo = local_roots / "template-import"
    repo.mkdir(parents=True, exist_ok=True)
    for dest, source_file in names.items():
        shutil.copyfile(origin / source_file, repo / dest)
    _git(repo, "init", "--quiet", "--initial-branch", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "template import")
    return repo


async def test_e2e_import_runs_against_the_canonical_template_too(
    db, seeded_catalog, mcp_allowlist, template_repo
):
    """The full import e2e against the template's own bytes (CI-safe: the
    fixture-copy parametrization always runs)."""
    from app.services.postings_service import sync_source as sync_job_source

    source = await _add(db, local_descriptor(template_repo))
    report = await sync_source(db, source.id)
    assert report["ok"] is True
    installed = await install_extension(
        db, source.id, "example-posting-fetcher", consent=True, actor_id=await _actor_id(db)
    )
    await lifecycle.set_install_enabled(db, uuid.UUID(installed["id"]), True)
    minted = (
        (await db.execute(select(JobSource).where(JobSource.key == "example-posting-fetcher")))
        .scalars()
        .first()
    )
    first = await sync_job_source(db, minted)
    assert first["errors"] == []
    assert first["synced"] == 3
    second = await sync_job_source(db, minted)
    assert second["synced"] == 0, "etag cursor honored from the imported spawn"
