"""Plan 142 amendment 2 — the INVERTED writer gate.

The original gate direction (assert the known writers call the seam)
only catches RENAMES. This one AST-scans the writer modules for posting
MUTATIONS — assignments to ``posting.<attr>``, ``setattr(posting, …)``,
``JobPosting(`` / ``PostingSkill(`` construction, and the
``posting_skills`` delete — and asserts every enclosing function IS
registered in the manifest below AND calls the journal seam. A writer
added outside the manifest fails the gate; a registered writer that
loses its seam call fails too.

The manifest (module → function → journal kind) is the registration
surface: adding a writer = extending this list.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

MODULES = {
    "postings_service": "app/services/postings/postings_service.py",
    "extract_service": "app/services/postings/extract_service.py",
    "detail_service": "app/services/postings/detail_service.py",
    "organization_service": "app/services/catalog/organization_service.py",
    "company_triage_service": "app/services/catalog/company_triage_service.py",
    "admin": "app/api/v1/admin.py",
}

#: Every posting-mutating function, by module — the registration surface.
MANIFEST: dict[str, dict[str, str]] = {
    "postings_service": {
        "upsert_posting": "sync_run",
        "map_posting": "retag",
        "decide_catalog": "retag",
        "expire_stale": "expiry",
    },
    "extract_service": {
        "apply_extract": "extract_llm",
        "_apply_extract_skills": "extract_llm",
    },
    "detail_service": {
        "merge_detail": "detail_fetch",
        "run_detail_enrichment": "detail_fetch",
    },
    "organization_service": {
        "attach_to_posting": "company_match",
        "merge": "company_match",
    },
    "company_triage_service": {
        "_relink_pending": "company_match",
    },
    "admin": {
        "manual_map_posting": "manual",
    },
}

#: Known-unrouted writers, asserted EXACT — normally empty. A writer lands
#: here only while its module is held by another session's uncommitted
#: wave (plan 142: `admin.manual_map_posting` sat here until the plan-144
#: wave committed the file); the moment the wave lands, move it into
#: MANIFEST with its `PostingChangeJournal.record` call. Any function
#: appearing here, or this set growing, fails the gate.
BLOCKED_WRITERS: set[tuple[str, str]] = set()


@dataclass
class _Scan:
    mutations: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    trees: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = field(
        default_factory=dict
    )


def _scan_source(module: str, source: str) -> _Scan:
    """Collect mutating functions and their defs in one module's source."""

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scan = _Scan()
            self.stack: list[str] = []

        def _mark(self, what: str) -> None:
            if self.stack:
                key = (module, self.stack[-1])
                self.scan.mutations.setdefault(key, set()).add(what)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if self.stack:
                self.scan.trees[(module, ".".join([*self.stack, node.name]))] = node
            else:
                self.scan.trees[(module, node.name)] = node
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def _posting_target(self, target: ast.expr) -> bool:
            return (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "posting"
            )

        def visit_Assign(self, node: ast.Assign) -> None:
            if any(self._posting_target(t) for t in node.targets):
                self._mark("assign")
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.target is not None and self._posting_target(node.target):
                self._mark("assign")
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if self._posting_target(node.target):
                self._mark("augassign")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in ("JobPosting", "PostingSkill"):
                    self._mark(f"ctor:{func.id}")
                elif (
                    func.id == "setattr"
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "posting"
                ):
                    self._mark("setattr")
                elif func.id == "update" and node.args:
                    first = node.args[0]
                    if (isinstance(first, ast.Name) and first.id == "JobPosting") or (
                        isinstance(first, ast.Attribute)
                        and isinstance(first.value, ast.Name)
                        and first.value.id == "JobPosting"
                        and first.attr in ("id", "status", "org_id", "raw")
                    ):
                        self._mark("bulk:update")
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "delete"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "__table__"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "PostingSkill"
            ):
                self._mark("delete:posting_skills")
            self.generic_visit(node)

    visitor = Visitor()
    visitor.visit(ast.parse(source))
    return visitor.scan


def _scan_repo_modules() -> _Scan:
    scan = _Scan()
    for module, rel in MODULES.items():
        part = _scan_source(module, (BACKEND / rel).read_text())
        scan.mutations.update(part.mutations)
        scan.trees.update(part.trees)
    return scan


def _calls_seam(node: ast.AST) -> bool:
    """Any `<x>.record(...)` call — the journal seam invocation."""
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "record"
        for child in ast.walk(node)
    )


def _violations(scan: _Scan, manifest: dict[str, dict[str, str]]) -> list[str]:
    problems: list[str] = []
    registered = {(module, fn) for module, fns in manifest.items() for fn in fns} | BLOCKED_WRITERS
    for key in scan.mutations:
        if key not in registered:
            problems.append(f"{key[0]}.{key[1]} mutates a posting but is not registered")
        elif key in BLOCKED_WRITERS:
            continue
        elif (tree := scan.trees.get(key)) is None or not _calls_seam(tree):
            problems.append(f"{key[0]}.{key[1]} is registered but never calls the seam")
    for module, fns in manifest.items():
        for fn in fns:
            if (module, fn) not in scan.mutations:
                problems.append(f"{module}.{fn} is registered but no longer mutates")
    return problems


# ------------------------------------------------------------------ tests


def test_manifest_exactly_covers_every_mutator():
    """The inverted direction: scan first, register second — an added
    writer that nobody registered fails here."""
    scan = _scan_repo_modules()
    assert not _violations(scan, MANIFEST)
    assert (
        set(scan.mutations)
        == {(module, fn) for module, fns in MANIFEST.items() for fn in fns} | BLOCKED_WRITERS
    )


def test_blocked_set_is_empty():
    """Every mutator is routed: no writer may linger unrouted (the set is
    the escape hatch ONLY while a module is another session's uncommitted
    work — assert it stays exactly empty)."""
    assert not BLOCKED_WRITERS


def test_gate_catches_a_new_unregistered_writer():
    """Proof the gate catches ADDITIONS (the plan-002 direction only
    caught removals): a fresh mutator outside the manifest fails."""
    scan = _scan_source(
        "postings_service",
        "async def sneaky_new_writer(db, posting):\n    posting.title = 'x'\n",
    )
    assert ("postings_service", "sneaky_new_writer") in scan.mutations
    assert _violations(scan, {}) == [
        "postings_service.sneaky_new_writer mutates a posting but is not registered"
    ]


def test_gate_catches_a_registered_writer_without_seam_call():
    scan = _scan_source(
        "detail_service",
        "async def merge_detail(posting, row):\n    posting.raw = {'d': 1}\n",
    )
    manifest = {"detail_service": {"merge_detail": "detail_fetch"}}
    assert _violations(scan, manifest) == [
        "detail_service.merge_detail is registered but never calls the seam"
    ]


def test_gate_accepts_a_registered_writer_with_seam_call():
    source = (
        "async def merge_detail(posting, row):\n"
        "    posting.raw = {'d': 1}\n"
        "    PostingChangeJournal.record(db, posting.id, 'detail_fetch')\n"
    )
    scan = _scan_source("detail_service", source)
    assert _violations(scan, {"detail_service": {"merge_detail": "detail_fetch"}}) == []


def test_gate_catches_setattr_and_ctor_mutations():
    scan = _scan_source(
        "extract_service",
        "def f(posting):\n"
        "    setattr(posting, 'title', 'x')\n"
        "def g(db):\n"
        "    return JobPosting(source_id=1, external_id='e', content_hash='h')\n"
        "def h(db, posting):\n"
        "    db.execute(PostingSkill.__table__.delete())\n",
    )
    assert {fn for _, fn in scan.mutations} == {"f", "g", "h"}
    assert scan.mutations[("extract_service", "f")] == {"setattr"}
    assert scan.mutations[("extract_service", "g")] == {"ctor:JobPosting"}
    assert scan.mutations[("extract_service", "h")] == {"delete:posting_skills"}


def test_gate_catches_bulk_update_statements():
    """A Core/ORM bulk UPDATE over job_postings is a posting mutation
    too — assignments the attribute scan can never see."""
    scan = _scan_source(
        "postings_service",
        "from sqlalchemy import update\n"
        "async def mass_expire(db):\n"
        "    await db.execute(update(JobPosting).values(status='expired'))\n"
        "async def by_id(db, pid):\n"
        "    await db.execute(update(JobPosting.id).values(x=1))\n"
        "async def benign(db):\n"
        "    await db.execute(update(JobSource).values(enabled=True))\n",
    )
    assert scan.mutations.get(("postings_service", "mass_expire")) == {"bulk:update"}
    assert ("postings_service", "benign") not in scan.mutations, (
        "non-posting bulk updates are not this gate's business"
    )


def test_stale_manifest_entry_fails():
    """Removing a writer from the code without pruning the manifest
    also fails (the manifest never lies)."""
    scan = _scan_source("postings_service", "async def nothing(db):\n    return\n")
    problems = _violations(scan, {"postings_service": {"upsert_posting": "sync_run"}})
    assert problems == ["postings_service.upsert_posting is registered but no longer mutates"]
