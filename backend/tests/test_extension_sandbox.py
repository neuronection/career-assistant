"""The T2 sandbox wall (plan 32 Phase 5 / ADR-0030's escape matrix ported
to Python — the threat model IS the acceptance criteria).

Real child processes, localhost/stdio only, bounded runtimes:

* the escape matrix: infinite loop ⇒ watchdog kill + self-disable; memory
  bomb ⇒ RLIMIT_AS cap enforced; path wander ⇒ typed path-denied; secret
  sniffing ⇒ env/fs denied, values cross host-side only; socket attempt ⇒
  audit-hook denial; undeclared-domain fetch ⇒ net-denied (all hops,
  redirect fixture included); quota exhaustion ⇒ typed budget, run ends
  cleanly; child crash (os._exit) ⇒ self-disable, others unaffected;
  protocol violations ⇒ typed protocol, recycled; version mismatch ⇒
  unsupported;
* the authoring story e2e: local git source → discovery → consent (the
  T2 sandbox disclosure VERBATIM) → install (tier T2, instance minted) →
  enable → postings sync through the sandbox → typed items land, state
  persists, audit rows exist;
* child unit checks: handshake echo, digest mismatch refusal, load
  failure + top-level escapes typed over the hello reply, clean dispose.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.encryption import encrypt_secret
from app.extensions import lifecycle
from app.extensions.registry import reset_registry
from app.extensions.runtime.sandbox import capabilities as cap_mod
from app.extensions.runtime.sandbox import host as sandbox_host
from app.extensions.runtime.sandbox.protocol import FramingError, validate_message
from app.models.enums import AITaskType
from app.models.extension_model import ExtensionInstall, ExtensionSandboxRun
from app.models.posting_model import JobPosting, JobSource

TESTS_DIR = Path(__file__).resolve().parent
REFERENCE_DIR = TESTS_DIR / "fixtures" / "t2_reference_extension"
CHILD_ENTRY = sandbox_host.child_entry()

SAMPLE_ROWS = [
    {"external_id": "row-1", "title": "Backend Engineer", "url": "https://example.jobs/1"},
    {"external_id": "row-2", "title": "Data Engineer", "url": "https://example.jobs/2"},
]


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def t2_env(tmp_path, monkeypatch):
    """Sandbox-tightened Settings + isolated data dir + clean shared quota
    state. The watchdog/memory knobs are tightened so the wall stays
    CI-fast; every spawned child is real."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "extension_local_source_roots", [str(tmp_path)])
    monkeypatch.setattr(settings, "extension_sandbox_call_timeout_seconds", 4.0)
    monkeypatch.setattr(settings, "extension_sandbox_spawn_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "extension_sandbox_dispose_timeout_seconds", 3.0)
    monkeypatch.setattr(settings, "extension_sandbox_max_concurrent", 2)
    monkeypatch.setattr(settings, "extension_sandbox_enabled", True)
    cap_mod.CapabilityProvider.reset_shared_state()
    reset_registry()
    yield tmp_path
    reset_registry()
    cap_mod.CapabilityProvider.reset_shared_state()


@pytest.fixture
async def mock_net(monkeypatch):
    """The polite runtime over an httpx.MockTransport — the sandbox's
    net.fetch rides the REAL host seam (guard, domain scope, robots),
    only the sockets are fake. Requests are captured for assertions."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404, text="no robots")
        if path == "/redir-evil":
            return httpx.Response(302, headers={"Location": "https://evil.example.jobs/x"})
        if path in ("/postings.json", "/secret.json"):
            return httpx.Response(200, json=SAMPLE_ROWS)
        return httpx.Response(404, text="nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=False)
    from app.extensions.runtime import http as http_runtime

    http_runtime._client = client
    http_runtime._robots = None
    yield seen
    from app.extensions.runtime.http import reset_runtime

    reset_runtime()
    await client.aclose()


def reference_manifest() -> dict:
    return json.loads((REFERENCE_DIR / "manifest.json").read_text())


def write_extension(root: Path, name: str, manifest: dict, entry: str | None) -> Path:
    """A real local git repo carrying one T2 artifact (manifest +
    extension.py). ``entry=None`` keeps the reference implementation."""
    import os

    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(repo.parent),
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
            },
        )

    shutil.copyfile(REFERENCE_DIR / "extension.py", repo / "extension.py")
    if entry is not None:
        (repo / "extension.py").write_text(entry, encoding="utf-8")
    (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    git("init", "--quiet", "--initial-branch", "main")
    git("add", ".")
    git("commit", "--quiet", "--allow-empty", "-m", "init")
    git("tag", "v1.0.0")
    return repo


def local_descriptor(repo: Path) -> dict:
    return {"local": {"path": str(repo)}, "ref": {"strategy": "branch", "value": "main"}}


async def install_t2(
    db,
    root: Path,
    name: str,
    manifest: dict,
    entry: str | None,
    ext_id: str | None = None,
) -> ExtensionInstall:
    """The full import path: local git source → discovery → consented
    install. Returns the install row (still disabled). ``ext_id``
    overrides the manifest id (extension ids are unique per DB)."""
    from app.extensions.lifecycle import add_source, install_extension, sync_source

    if ext_id is not None:
        manifest = {**manifest, "id": ext_id}
    repo = write_extension(root, name, manifest, entry)
    source_view = await add_source(db, local_descriptor(repo))
    report = await sync_source(db, source_view["id"])
    assert report["ok"] is True, report
    [candidate] = report["candidates"]
    assert candidate["compatible"] is True, candidate
    await install_extension(
        db, source_view["id"], manifest["id"], consent=True, data_dir=root / "data"
    )
    row = (
        (
            await db.execute(
                select(ExtensionInstall).where(ExtensionInstall.extension_id == manifest["id"])
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    return row


async def enable_and_sync(db, install: ExtensionInstall, **secrets) -> dict:
    """Enable (the explicit admin act) + one postings sync through the
    sandbox."""
    from app.services.postings_service import sync_source

    await _set_enabled(db, install)
    row = await _job_source(db, install)
    if secrets:
        row.secrets = {slot: encrypt_secret(value) for slot, value in secrets.items()}
        await db.commit()
    return await sync_source(db, row)


async def _job_source(db, install: ExtensionInstall) -> JobSource:
    row = (
        (await db.execute(select(JobSource).where(JobSource.key == install.extension_id)))
        .scalars()
        .first()
    )
    assert row is not None, "the minted instance exists"
    return row


async def _set_enabled(db, install: ExtensionInstall) -> None:
    from app.extensions.lifecycle import set_install_enabled

    await set_install_enabled(db, install.id, True)


async def _posted_external_ids(db, install: ExtensionInstall) -> set[str]:
    source = await _job_source(db, install)
    rows = (
        (await db.execute(select(JobPosting.external_id).where(JobPosting.source_id == source.id)))
        .scalars()
        .all()
    )
    return set(rows)


# ------------------------------------------------------------- the escapes


async def test_escape_infinite_loop_watchdog_kills_and_self_disables(db, t2_env):
    manifest = reference_manifest()
    entry = "def fetch(config, state):\n    while True:\n        pass\n"
    install = await install_t2(db, t2_env, "loop-bomb", manifest, entry)
    report = await enable_and_sync(db, install)
    assert report["synced"] == 0
    [error] = report["errors"]
    assert error["code"] == "provider"
    assert "watchdog" in error["detail"]
    await db.refresh(install)
    assert install.state == "self-disabled"
    assert not install.enabled
    source = await _job_source(db, install)
    assert not source.enabled
    # The surfaced reason rides BOTH the lifecycle state and the typed
    # error on the minted instance (the admin sees exactly what happened).
    assert "watchdog" in (source.error or ""), "the reason is surfaced"


async def test_escape_memory_bomb_capped(db, t2_env, monkeypatch, mock_net):
    """The address-space cap holds: the bomb dies of MemoryError inside the
    sandbox — contained either way (a clean typed error, or a crash that
    self-disables); the host is unaffected in both."""
    monkeypatch.setattr(settings, "extension_sandbox_memory_mb", 96)
    manifest = reference_manifest()
    entry = (
        "def fetch(config, state):\n"
        "    bomb = []\n"
        "    while True:\n"
        "        bomb.extend([b'x' * (1024 * 1024)] * 64)\n"
    )
    install = await install_t2(db, t2_env, "memory-bomb", manifest, entry)
    report = await enable_and_sync(db, install)
    assert report["synced"] == 0
    detail = " ".join(error["detail"] for error in report["errors"])
    await db.refresh(install)
    contained = "MemoryError" in detail or install.state == "self-disabled"
    assert contained, f"the cap must contain the bomb (detail: {detail})"

    healthy = await install_t2(
        db, t2_env, "memory-after", reference_manifest(), None, ext_id="memory-after"
    )
    assert (await enable_and_sync(db, healthy))["synced"] == len(SAMPLE_ROWS), (
        "the host and other extensions are unaffected"
    )


async def test_escape_path_wander_denied_typed(db, t2_env, mock_net):
    manifest = reference_manifest()
    entry = "\n".join(
        [
            "from capability import items_emit",
            "import codecs",
            "def fetch(config, state):",
            "    findings = []",
            "    for attempt in ('open', 'listdir', 'write', 'read-contents'):",
            "        try:",
            "            if attempt == 'open':",
            "                codecs.open('/etc/passwd').read()",
            "                findings.append('open:ALLOWED')",
            "            elif attempt == 'listdir':",
            "                import os",
            "                os.listdir('/')",
            "                findings.append('listdir:ALLOWED')",
            "            elif attempt == 'write':",
            "                codecs.open('/tmp/pwned', 'w').write('x')",
            "                findings.append('write:ALLOWED')",
            "            else:",
            "                # content read of a guessed path — the actual",
            "                # exfiltration surface (stat is metadata-only and",
            "                # carries no CPython audit event: disclosed residual)",
            "                codecs.open('/etc/shadow').read()",
            "                findings.append('read:ALLOWED')",
            "        except Exception as exc:",
            "            findings.append(attempt + ':' + str(getattr(exc, 'code', 'x')))",
            "    items_emit([",
            "        {'external_id': f, 'title': 'probe'} for f in findings",
            "    ])",
            "    return {}",
        ]
    )
    install = await install_t2(db, t2_env, "path-wander", manifest, entry)
    report = await enable_and_sync(db, install)
    assert report["synced"] == 4, "all four probes ran"
    assert report["errors"] == []
    probes = await _posted_external_ids(db, install)
    assert probes == {
        "open:path-denied",
        "listdir:path-denied",
        "write:path-denied",
        "read-contents:path-denied",
    }, "every filesystem content access is denied typed (no fs capability exists)"


async def test_escape_secret_sniffing_contained(db, t2_env, mock_net):
    """The child cannot read env or host files; the declared slot resolves
    to a PLACEHOLDER and the value crosses host→upstream only."""
    manifest = reference_manifest()
    manifest["capabilities"] = ["sync", "net", "state", "secrets"]
    manifest["secrets"] = [{"id": "api-token", "purpose": "board token"}]
    entry = "\n".join(
        [
            "from capability import items_emit, net_fetch, secrets_need",
            "def fetch(config, state):",
            "    findings = []",
            "    try:",
            "        import os",
            "        leak = os.environ.get('CAREER_DATA_KEY')",
            "        findings.append('env:' + ('EMPTY' if leak is None else 'LEAKED'))",
            "    except Exception as exc:",
            "        findings.append('env:' + str(getattr(exc, 'code', 'x')))",
            "    try:",
            "        import os",
            "        os.putenv('CAREER_DATA_KEY', 'x')",
            "        findings.append('putenv:ALLOWED')",
            "    except Exception as exc:",
            "        findings.append('putenv:' + str(getattr(exc, 'code', 'x')))",
            "    try:",
            "        import codecs",
            "        codecs.open('/proc/self/environ').read()",
            "        findings.append('fs:ALLOWED')",
            "    except Exception as exc:",
            "        findings.append('fs:' + str(getattr(exc, 'code', 'x')))",
            "    placeholder = secrets_need('api-token')",
            "    response = net_fetch(",
            "        config['url'], headers={'Authorization': 'Bearer ' + placeholder},",
            "    )",
            "    items_emit(["
            "{'external_id': 'got:' + placeholder, 'title': response['body'][:1]}])",
            "    items_emit([{'external_id': f, 'title': 'probe'} for f in findings])",
            "    return {}",
        ]
    )
    install = await install_t2(db, t2_env, "sniffer", manifest, entry)
    report = await enable_and_sync(db, install, **{"api-token": "super-secret-value-99"})
    assert report["synced"] == 4
    probes = await _posted_external_ids(db, install)
    assert "env:EMPTY" in probes, (
        "the host env never crosses the seam (scrubbed at spawn) — nothing to sniff"
    )
    assert "putenv:invalid" in probes, "environment writes are denied at the audit wall"
    assert "fs:path-denied" in probes, "host file reads are denied at the audit wall"
    assert "got:{{secret:api-token}}" in probes, (
        "secrets.need returns the placeholder, never the value"
    )
    authorized = [r for r in mock_net if r.headers.get("authorization")]
    assert authorized, "the authenticated fetch happened"
    assert authorized[0].headers["authorization"] == "Bearer super-secret-value-99", (
        "the host substituted the real value into the upstream request host-side"
    )


async def test_escape_secret_gates_undeclared_and_unresolved(db, t2_env):
    """The seam's secret gates, probed at the provider (the sync pre-check
    already blocks unresolved REQUIRED slots upstream — D19)."""
    manifest = reference_manifest()
    manifest["secrets"] = [{"id": "api-token", "purpose": "board token"}]
    install = await install_t2(db, t2_env, "secret-gates", manifest, None)
    from app.extensions.runtime.sandbox.capabilities import SeamError

    provider = cap_mod.CapabilityProvider(db=db, install=install, secrets={})
    with pytest.raises(SeamError) as excinfo:
        await provider.handle("cap.secrets.need", {"slot": "api-token"})
    assert excinfo.value.code == "needs-secret"
    with pytest.raises(SeamError) as excinfo:
        await provider.handle("cap.secrets.need", {"slot": "undeclared-slot"})
    assert excinfo.value.code == "invalid"


async def test_escape_socket_attempt_denied(db, t2_env, mock_net):
    manifest = reference_manifest()
    entry = "\n".join(
        [
            "from capability import items_emit",
            "def fetch(config, state):",
            "    findings = []",
            "    try:",
            "        import socket",
            "        socket.socket()",
            "        findings.append('socket:ALLOWED')",
            "    except Exception as exc:",
            "        findings.append('socket:' + str(getattr(exc, 'code', 'x')))",
            "    try:",
            "        import subprocess",
            "        findings.append('subprocess:ALLOWED')",
            "    except Exception as exc:",
            "        findings.append('subprocess:' + str(getattr(exc, 'code', 'x')))",
            "    items_emit([{'external_id': f, 'title': 'probe'} for f in findings])",
            "    return {}",
        ]
    )
    install = await install_t2(db, t2_env, "socket-try", manifest, entry)
    await enable_and_sync(db, install)
    probes = await _posted_external_ids(db, install)
    assert "subprocess:unsupported" in probes, "subprocess import is outside the frozen surface"
    assert any(p.startswith("socket:") for p in probes)
    assert "socket:ALLOWED" not in probes, "no socket was ever created"


async def test_escape_undeclared_domain_net_denied_all_hops(db, t2_env, mock_net):
    manifest = reference_manifest()
    entry = "\n".join(
        [
            "from capability import items_emit, net_fetch",
            "def fetch(config, state):",
            "    findings = []",
            "    for url in (",
            "        'https://other.example.jobs/x', 'https://example.jobs/redir-evil'",
            "    ):",
            "        try:",
            "            net_fetch(url)",
            "            findings.append(url + ':ALLOWED')",
            "        except Exception as exc:",
            "            findings.append(str(getattr(exc, 'code', 'x')))",
            "    items_emit([{'external_id': f, 'title': 'probe'} for f in findings])",
            "    return {}",
        ]
    )
    install = await install_t2(db, t2_env, "domain-scope", manifest, entry)
    await enable_and_sync(db, install)
    probes = await _posted_external_ids(db, install)
    assert probes == {"net-denied"}, (
        "undeclared hosts AND redirect hops outside the declared scope are net-denied"
    )


async def test_escape_quota_exhaustion_budget_ends_cleanly(db, t2_env, monkeypatch, mock_net):
    """Quota exhaustion is typed ``budget`` on the refused calls (visible
    in the audit rows) and the run ends CLEANLY — dispose, exit 0, no
    self-disable."""
    monkeypatch.setattr(settings, "extension_sandbox_calls_per_minute", 3)
    manifest = reference_manifest()
    entry = "\n".join(
        [
            "from capability import state_get",
            "def fetch(config, state):",
            "    for _ in range(6):",
            "        try:",
            "            state_get('seen')",
            "        except Exception:",
            "            pass",
            "    return {}",
        ]
    )
    install = await install_t2(db, t2_env, "quota-run", manifest, entry)
    report = await enable_and_sync(db, install)
    assert report["synced"] == 0
    await db.refresh(install)
    assert install.state == "installed", "quota exhaustion never self-disables"
    from app.models.ai_model import AIGeneration

    audits = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.SANDBOX_CAPABILITY_CALL.value,
                    AIGeneration.model == install.extension_id,
                )
            )
        )
        .scalars()
        .all()
    )
    ok = [a for a in audits if a.status == "ok"]
    budgeted = [a for a in audits if a.error == "budget"]
    assert len(ok) == 3, "the first three calls were served"
    assert len(budgeted) >= 1, "the rest were refused typed budget — never a silent drop"


async def test_escape_child_crash_self_disables_others_unaffected(db, t2_env, mock_net):
    manifest = reference_manifest()
    crash_entry = (
        "import os\n"
        "from capability import items_emit\n"
        "def fetch(config, state):\n"
        "    items_emit([{'external_id': 'before-crash', 'title': 'x'}])\n"
        "    os._exit(9)\n"
    )
    crashed = await install_t2(db, t2_env, "crasher", manifest, crash_entry)
    report = await enable_and_sync(db, crashed)
    assert report["synced"] == 0
    [error] = report["errors"]
    assert error["code"] == "provider"
    await db.refresh(crashed)
    assert crashed.state == "self-disabled"

    # The host and the OTHER extension are unaffected.
    healthy = await install_t2(
        db,
        t2_env,
        "healthy-after-crash",
        reference_manifest(),
        None,
        ext_id="healthy-after-crash",
    )
    assert (await enable_and_sync(db, healthy))["synced"] == len(SAMPLE_ROWS)
    await db.refresh(crashed)
    assert crashed.state == "self-disabled", "the crash stays contained"


async def test_escape_protocol_violations_typed_and_recycled(db, t2_env, monkeypatch):
    """A child emitting garbage lines is recycled at three violations —
    typed ``protocol`` (the host's violation machinery, driven against a
    stub child)."""
    stub = t2_env / "garbage_child.py"
    stub.write_text(
        "import sys, time\n"
        "sys.stdin.readline()\n"
        "for _ in range(3):\n"
        "    sys.stdout.write('not json at all\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sandbox_host, "child_entry", lambda: stub)
    install = await install_t2(db, t2_env, "garbage", reference_manifest(), None)
    await _set_enabled(db, install)
    row = await _job_source(db, install)
    from app.extensions.registry import resolve_connector

    connector = await resolve_connector(db, row.connector_key)
    result = await connector.fetch(row.config, {})
    [error] = result.partial_errors
    assert error.code == "protocol", f"got {error.code}: {error.detail}"
    assert "protocol violations" in error.detail
    await db.refresh(install)
    assert install.state == "installed", (
        "recycling is THIS run's failure; the extension survives it (a fresh child spawns next run)"
    )


async def test_escape_wrong_handshake_version_unsupported(db, t2_env, monkeypatch):
    """Protocol-VERSION mismatch at the handshake: terminate + self-disable
    with ``unsupported`` — never half-runs (capability-rpc.md §2)."""
    stub = t2_env / "wrong_version_child.py"
    stub.write_text(
        "import json, sys\n"
        "line = sys.stdin.readline()\n"
        "doc = json.loads(line)\n"
        "sys.stdout.write(json.dumps({'v': 2, 'type': 'result', 'id': doc['id'],\n"
        "                             'result': {'output': {}}}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.readline()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sandbox_host, "child_entry", lambda: stub)
    install = await install_t2(db, t2_env, "wrongver", reference_manifest(), None)
    await _set_enabled(db, install)
    row = await _job_source(db, install)
    from app.extensions.registry import resolve_connector

    connector = await resolve_connector(db, row.connector_key)
    result = await connector.fetch(row.config, {})
    [error] = result.partial_errors
    assert error.code == "unsupported", f"got {error.code}: {error.detail}"
    assert "version mismatch" in error.detail
    await db.refresh(install)
    assert install.state == "self-disabled"


async def test_disabled_tier_refuses_to_spawn(db, t2_env, monkeypatch, mock_net):
    monkeypatch.setattr(settings, "extension_sandbox_enabled", False)
    install = await install_t2(db, t2_env, "disabled-tier", reference_manifest(), None)
    report = await enable_and_sync(db, install)
    assert report["synced"] == 0
    [error] = report["errors"]
    assert error["code"] == "unsupported"
    await db.refresh(install)
    assert install.state == "self-disabled"


# ------------------------------------------------------- the authoring story


async def test_reference_extension_e2e(db, t2_env, mock_net):
    """import → consent (T2 disclosure VERBATIM) → sandboxed run → typed
    items + state + audit rows + the cursor short-circuit."""
    manifest = reference_manifest()
    entry = (REFERENCE_DIR / "extension.py").read_text()
    install = await install_t2(db, t2_env, "reference", manifest, entry)
    assert install.tier == "T2"
    [consent] = install.consents
    assert consent["tier"] == "T2"
    assert consent["disclosureKey"] == "t2SandboxDisclosure"
    assert consent["disclosure"] == lifecycle.t2_sandbox_disclosure(), (
        "the charter's sandbox disclosure renders VERBATIM"
    )

    report = await enable_and_sync(db, install)
    assert report["synced"] == len(SAMPLE_ROWS), f"both rows land typed: {report}"
    assert report["errors"] == []
    await db.refresh(install)
    assert install.extension_state.get("seen") == ["row-1", "row-2"], (
        "cap.state.get/set persist on the install row"
    )
    source = await _job_source(db, install)
    assert source.sync_state.get("fetched") == len(SAMPLE_ROWS), "next_state round-trips"

    from app.services.postings_service import sync_source

    second = await sync_source(db, source)
    assert second["synced"] == 0, "the dedupe state short-circuits the second run"

    from app.models.ai_model import AIGeneration

    audits = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.SANDBOX_CAPABILITY_CALL.value,
                    AIGeneration.model == install.extension_id,
                )
            )
        )
        .scalars()
        .all()
    )
    methods = {str(a.prompt).rsplit(":", 1)[-1] for a in audits}
    assert "cap.net.fetch" in methods and "cap.items.emit" in methods, (
        "one audit row per capability call, through the funnel"
    )
    assert all(a.provider == "sandbox" for a in audits)
    runs = (
        (
            await db.execute(
                select(ExtensionSandboxRun).where(ExtensionSandboxRun.install_id == install.id)
            )
        )
        .scalars()
        .all()
    )
    assert runs and all(r.outcome == "completed" for r in runs), (
        f"run records close cleanly: {[(r.outcome, r.reason[:80]) for r in runs]}"
    )


async def test_extension_state_quota_is_enforced(db, t2_env):
    install = await install_t2(db, t2_env, "state-quota", reference_manifest(), None)
    provider = cap_mod.CapabilityProvider(db=db, install=install)
    with pytest.raises(cap_mod.SeamError) as excinfo:
        provider._state_set({"key": "big", "value": "x" * 300_000})
    assert excinfo.value.code == "budget"


async def test_concurrent_sandbox_cap_is_budget(db, t2_env, monkeypatch, mock_net):
    monkeypatch.setattr(settings, "extension_sandbox_max_concurrent", 1)
    holder = await install_t2(
        db,
        t2_env,
        "cap-holder",
        reference_manifest(),
        "def fetch(config, state):\n    while True:\n        pass\n",
    )
    await _set_enabled(db, holder)
    holder_row = await _job_source(db, holder)
    from app.extensions.registry import resolve_connector

    holder_connector = await resolve_connector(db, holder_row.connector_key)
    holder_task = asyncio.create_task(holder_connector.fetch(holder_row.config, {}))
    (await asyncio.sleep(1.0),)  # the holder's sandbox is live now

    second = await install_t2(
        db, t2_env, "cap-second", reference_manifest(), None, ext_id="cap-second"
    )
    await _set_enabled(db, second)
    second_row = await _job_source(db, second)
    second_connector = await resolve_connector(db, second_row.connector_key)
    result = await second_connector.fetch(second_row.config, {})
    [error] = result.partial_errors
    assert error.code == "budget", "over the cap is typed budget, never a queue"
    holder_result = await holder_task
    assert holder_result.partial_errors, "the holder finished (watchdog), cap released"


async def test_boot_reconciliation_interrupts_orphans(db, t2_env):
    from datetime import UTC, datetime

    from app.extensions.runtime.sandbox import interrupt_orphans

    install = await install_t2(db, t2_env, "orphan", reference_manifest(), None)
    run = ExtensionSandboxRun(
        install_id=install.id,
        extension_id=install.extension_id,
        digest=install.digest,
        pid=999999,
    )
    db.add(run)
    await db.commit()
    assert await interrupt_orphans(db) == 1
    await db.flush()
    await db.refresh(run)
    assert run.outcome == "interrupted"
    assert run.ended_at is not None
    assert datetime.now(UTC) >= run.ended_at
    await db.refresh(install)
    assert install.state == "installed", "host death is never extension failure — no self-disable"
    assert await interrupt_orphans(db) == 0, "reconciliation is idempotent"


async def test_host_watchdog_covers_hung_capability_dispatch(db, t2_env):
    """The wall-clock watchdog also covers a hung host-side capability
    DISPATCH, not just the extension's invoke."""

    async def hang(method, params):
        await asyncio.sleep(60)

    await install_t2(db, t2_env, "hang-dispatch", reference_manifest(), None)
    stub_provider = type(
        "P",
        (),
        {
            "handle": staticmethod(hang),
        },
    )()
    stub_proc = type("Proc", (), {"returncode": None, "kill": lambda self: None})()
    session = sandbox_host._SandboxSession(
        stub_proc,  # type: ignore[arg-type]
        stub_provider,
        sandbox_host.SandboxLimits(
            call_timeout_s=0.2,
            spawn_timeout_s=1,
            dispose_timeout_s=1,
            memory_mb=512,
            max_concurrent=2,
        ),
        run_row=type("R", (), {"id": None, "ended_at": None})(),
        expected_identity={},
    )
    # The death is recorded on the session (the run loop surfaces it when
    # the pending invoke fails on EOF).
    await session._serve(
        {"v": 1, "type": "call", "id": "x", "method": "cap.state.get", "params": {}}, "x"
    )
    assert session.death is not None and session.death.outcome == "watchdog"


# --------------------------------------------------------- child unit checks


def _spawn(content_dir: Path, digest: str, stdin_bytes: bytes, timeout: float = 20.0):
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(CHILD_ENTRY),
            "--protocol",
            "capability-rpc/1",
            "--content-dir",
            str(content_dir),
            "--entry",
            "extension.py",
            "--digest",
            digest,
        ],
        input=stdin_bytes,
        capture_output=True,
        timeout=timeout,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(content_dir)},
    )


def _digest_of(path: Path) -> str:
    return lifecycle.digest_tree(path)


def _hello_line(mid: str = "h1") -> bytes:
    return (
        json.dumps(
            {
                "v": 1,
                "type": "call",
                "id": mid,
                "method": "ext.invoke",
                "params": {"op": "hello", "input": {}},
            }
        ).encode()
        + b"\n"
    )


def test_child_hello_echoes_pinned_identity(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(REFERENCE_DIR, content)
    digest = _digest_of(content)
    proc = _spawn(content, digest, _hello_line())
    assert proc.returncode == 0, proc.stderr.decode()[:500]
    reply = json.loads(proc.stdout.decode().splitlines()[0])
    assert reply["type"] == "result"
    assert reply["result"]["output"] == {
        "id": "t2-reference-scorer",
        "version": "1.0.0",
        "digest": digest,
    }


def test_child_refuses_unpinned_content(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(REFERENCE_DIR, content)
    proc = _spawn(content, "0" * 64, _hello_line())
    assert proc.returncode == 2, "digest mismatch refuses before any extension byte runs"
    assert proc.stdout == b""


def test_child_load_failure_typed_over_hello(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(REFERENCE_DIR, content)
    (content / "extension.py").write_text("this is not python (\n", encoding="utf-8")
    proc = _spawn(content, _digest_of(content), _hello_line())
    assert proc.returncode == 0
    reply = json.loads(proc.stdout.decode().splitlines()[0])
    assert reply["type"] == "error"
    assert reply["error"]["code"] == "invalid"
    assert reply["error"]["detail"] == '{"stage": "load"}'


def test_child_top_level_escape_is_typed_over_hello(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(REFERENCE_DIR, content)
    # An indirect open through a startup-cached stdlib module reaches the
    # audit wall (direct ``open`` is simply absent from the restricted
    # builtins — the outer layer).
    (content / "extension.py").write_text(
        "import codecs\ncodecs.open('/etc/passwd')\n", encoding="utf-8"
    )
    proc = _spawn(content, _digest_of(content), _hello_line())
    assert proc.returncode == 0
    reply = json.loads(proc.stdout.decode().splitlines()[0])
    assert reply["type"] == "error"
    assert reply["error"]["code"] == "path-denied"


def test_child_dispose_exits_zero(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(REFERENCE_DIR, content)
    lines = (
        _hello_line()
        + json.dumps(
            {
                "v": 1,
                "type": "call",
                "id": "d",
                "method": "ext.dispose",
                "params": {},
            }
        ).encode()
        + b"\n"
    )
    proc = _spawn(content, _digest_of(content), lines)
    assert proc.returncode == 0
    replies = proc.stdout.decode().splitlines()
    assert json.loads(replies[0])["type"] == "result"
    assert json.loads(replies[1])["result"] == {}


# ------------------------------------------------------- protocol seam unit


def test_seam_rejects_unknown_methods():
    doc = {"v": 1, "type": "call", "id": 1, "method": "cap.fs.read", "params": {}}
    with pytest.raises(FramingError):
        validate_message(json.dumps(doc))


# ------------------------------------------------------- frozen-packaging runtime check


async def test_connector_rides_kill_switch_on_unavailable_runtime(db, t2_env, monkeypatch):
    """The frozen-packaging capability check (plan 32 Phase 5 follow-up):
    a host with no spawnable interpreter/child assets (the PyInstaller
    case — mocked here, the detection logic has its own suite in
    tests/test_extension_sandbox_runtime.py) self-disables the T2
    instance with the surfaced remedy and a typed ``unsupported``
    partial error — the Phase-5 kill-switch path, host unaffected."""
    from app.extensions.runtime.sandbox import SandboxRuntimeUnavailable
    from app.extensions.runtime.sandbox import runtime as sandbox_runtime
    from app.extensions.runtime.sandbox.connector import SandboxConnector
    from app.models.extension_model import ExtensionInstall

    install = ExtensionInstall(
        extension_id="runtime-less",
        manifest={
            "capabilities": [],
            "i18n": {"locales": {"en": {"title": "Runtime-less"}}},
        },
        pin_ref="main",
        digest="0" * 64,
        content_path=str(t2_env),
        tier="T2",
        state="installed",
        enabled=True,
    )
    db.add(install)
    await db.flush()

    def unavailable(*_a: object, **_kw: object) -> None:
        raise SandboxRuntimeUnavailable(sandbox_runtime._REMEDY)

    monkeypatch.setattr(sandbox_runtime, "check_sandbox_runtime", unavailable)

    disabled: list[str] = []

    async def fake_self_disable(self, reason: str) -> None:
        disabled.append(reason)

    monkeypatch.setattr(SandboxConnector, "_self_disable", fake_self_disable)

    connector = SandboxConnector(db, install)
    result = await connector.fetch({}, {})
    [error] = result.partial_errors
    assert error.code == "unsupported"
    assert "run-dev.sh" in error.detail, "the remedy crosses to the admin surface"
    assert disabled and disabled[0].startswith("unsupported: "), (
        "the lifecycle reason carries the surfaced remedy"
    )
    assert result.items == []
