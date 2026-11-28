"""Pin the on-demand test selection and the path classifier (plan 227 T4).

The selection is iteration tooling, never a gate: these cases pin the path
sets, the always-run set, the static importer mapping (including parent-package
imports), the full-suite triggers, the no-importer warning and the fact that no
workflow wires the selection in.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
CHANGED_TESTS = ROOT / "scripts" / "changed-tests.py"
CHANGED_PATHS = ROOT / "scripts" / "changed-paths.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_ALWAYS_RUN = {
    "tests/test_quality_gates.py",
    "tests/test_docs_claims.py",
    "tests/test_config_contract.py",
    "tests/test_test_harness.py",
    "tests/test_ci_shards.py",
    "tests/test_ci_selection.py",
    "tests/test_no_private_integration_mentions.py",
}
EXPECTED_BACKEND_READ = {
    "backend/",
    "contracts/",
    "docs/user/",
    "docs/dev/",
    "scripts/",
    "docker/",
    "packaging/",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
}
EXPECTED_FRONTEND = {
    "frontend/",
    "frontend/package.json",
    "frontend/package-lock.json",
}
EXPECTED_FULL_SUITE_FILES = {
    "backend/pyproject.toml",
    "uv.lock",
    "backend/tests/conftest.py",
    "backend/tests/seed_pack_fixture.py",
    ".github/workflows/ci.yml",
}
EXPECTED_FULL_SUITE_DIRS = {
    "backend/alembic/",
    "contracts/",
    "docs/user/",
    "docs/dev/",
    "scripts/",
}


def _load(name: str, path: Path) -> ModuleType:
    """Import a dashed script file as a module.

    Args:
        name: module name to register.
        path: script path.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=1)
def _changed_tests() -> ModuleType:
    """Import ``scripts/changed-tests.py`` once."""
    return _load("changed_tests", CHANGED_TESTS)


@functools.lru_cache(maxsize=1)
def _changed_paths() -> ModuleType:
    """Import ``scripts/changed-paths.py`` once."""
    return _load("changed_paths", CHANGED_PATHS)


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a script with the current interpreter.

    Args:
        script: script path.
        *args: command-line arguments.

    Returns:
        The completed process.
    """
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _diff_file(tmp_path: Path, *paths: str) -> Path:
    """Write a synthetic diff file.

    Args:
        tmp_path: pytest temporary directory.
        *paths: repo-relative changed paths.

    Returns:
        The diff file path.
    """
    target = tmp_path / "diff.txt"
    target.write_text("\n".join(paths) + "\n", encoding="utf-8")
    return target


def test_the_always_run_set_names_existing_test_files() -> None:
    for relative in _changed_tests().ALWAYS_RUN:
        assert (BACKEND / relative).is_file(), relative


def test_the_always_run_set_keeps_the_meta_gates() -> None:
    assert set(_changed_tests().ALWAYS_RUN) >= EXPECTED_ALWAYS_RUN


def test_the_full_suite_triggers_name_real_paths() -> None:
    module = _changed_tests()
    assert set(module.FULL_SUITE_FILES) >= EXPECTED_FULL_SUITE_FILES
    assert set(module.FULL_SUITE_DIRS) >= EXPECTED_FULL_SUITE_DIRS
    for relative in EXPECTED_FULL_SUITE_FILES:
        assert (ROOT / relative).is_file(), relative
    for prefix in EXPECTED_FULL_SUITE_DIRS:
        assert (ROOT / prefix).is_dir(), prefix


def test_the_importer_mapping_selects_direct_and_parent_package_imports() -> None:
    module = _changed_tests()
    imports = {
        "app.services.deep": {"tests/test_deep.py"},
        "app.services": {"tests/test_package.py"},
        "app.other": {"tests/test_other.py"},
    }
    assert module.select_for_module("app.services.deep", imports) == {
        "tests/test_deep.py",
        "tests/test_package.py",
    }


def test_a_changed_package_selects_submodule_importers() -> None:
    module = _changed_tests()
    imports = {"app.services.deep": {"tests/test_deep.py"}}
    assert module.select_for_module("app.services", imports) == {"tests/test_deep.py"}


def test_module_for_path_handles_packages_and_non_python_files() -> None:
    module = _changed_tests()
    assert module.module_for_path("backend/app/a/b.py") == "app.a.b"
    assert module.module_for_path("backend/app/a/b/__init__.py") == "app.a.b"
    assert module.module_for_path("backend/app/__init__.py") == "app"
    assert module.module_for_path("backend/app/data/probe.json") is None
    assert module.module_for_path("frontend/src/App.tsx") is None


def test_a_changed_test_module_selects_itself_and_the_always_run_set(tmp_path: Path) -> None:
    completed = _run(
        CHANGED_TESTS,
        "--diff-file",
        str(_diff_file(tmp_path, "backend/tests/test_jobs.py")),
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["full_suite"] is False
    assert "tests/test_jobs.py" in payload["selected"]
    assert set(_changed_tests().ALWAYS_RUN) <= set(payload["selected"])


def test_no_importer_warns_and_keeps_only_the_always_run_set(tmp_path: Path) -> None:
    completed = _run(
        CHANGED_TESTS,
        "--diff-file",
        str(_diff_file(tmp_path, "backend/app/probe/definitely_missing.py")),
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["full_suite"] is False
    assert set(payload["selected"]) == set(_changed_tests().ALWAYS_RUN)
    assert payload["missing_importers"] == ["app.probe.definitely_missing"]
    assert "no importer" in completed.stderr


def test_a_full_suite_trigger_selects_every_test_file(tmp_path: Path) -> None:
    completed = _run(
        CHANGED_TESTS,
        "--diff-file",
        str(_diff_file(tmp_path, "backend/alembic/versions/0001_probe.py")),
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["full_suite"] is True
    assert "backend/alembic/" in payload["reason"]
    assert len(payload["selected"]) == payload["total_test_files"]
    assert "tests/test_admin.py" in payload["selected"]


def test_the_selection_is_not_wired_into_the_workflow() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "changed-tests" not in workflow
    assert "changed-paths" not in workflow


def test_the_path_classifier_sets_keep_their_contract() -> None:
    module = _changed_paths()
    assert not module.missing_required_paths(
        module.REQUIRED_BACKEND_READ, module.BACKEND_READ_PATHS
    )
    assert not module.missing_required_paths(module.REQUIRED_FRONTEND, module.FRONTEND_PATHS)
    assert set(module.REQUIRED_BACKEND_READ) == EXPECTED_BACKEND_READ
    assert set(module.REQUIRED_FRONTEND) == EXPECTED_FRONTEND


def test_a_missing_backend_read_path_fails_the_contract() -> None:
    module = _changed_paths()
    reduced = tuple(path for path in module.BACKEND_READ_PATHS if path != "backend/")
    assert module.missing_required_paths(module.REQUIRED_BACKEND_READ, reduced) == ["backend/"]


def test_the_classifier_classes_backend_frontend_and_docs_diffs() -> None:
    module = _changed_paths()
    backend = module.classify_paths(["backend/app/x.py"])
    assert backend["backend"] is True
    assert backend["frontend"] is False
    assert backend["skippable_backend"] is False

    frontend = module.classify_paths(["frontend/src/App.tsx"])
    assert frontend["backend"] is False
    assert frontend["frontend"] is True
    assert frontend["skippable_backend"] is True

    user_docs = module.classify_paths(["docs/user/guide.md"])
    assert user_docs["backend"] is True
    assert user_docs["docs"] is True
    assert user_docs["skippable_backend"] is False

    plain_docs = module.classify_paths(["docs/deploy.md"])
    assert plain_docs["backend"] is False
    assert plain_docs["docs"] is True


def test_the_classifier_fails_closed_on_unknown_paths() -> None:
    module = _changed_paths()
    result = module.classify_paths(["unknown/file.txt"])
    assert result["backend"] is True
    assert result["skippable_backend"] is False
    assert result["unknown"] == ["unknown/file.txt"]


def test_the_classifier_reads_a_synthetic_diff_file(tmp_path: Path) -> None:
    completed = _run(
        CHANGED_PATHS,
        "--diff-file",
        str(_diff_file(tmp_path, "frontend/src/App.tsx")),
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["backend"] is False
    assert payload["frontend"] is True


def test_the_classifier_self_check_passes() -> None:
    completed = _run(CHANGED_PATHS, "--check")
    assert completed.returncode == 0, completed.stderr
    assert "self-check ok" in completed.stdout
