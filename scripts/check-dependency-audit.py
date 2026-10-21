#!/usr/bin/env python3
"""Blocking dependency-audit gate with a reviewed advisory allowlist.

Plan 124.1: `pip-audit` and `npm audit` are gates, not advisories. Every
finding above the severity floor blocks unless it is listed in
``security/dependency-audit-allowlist.json`` with a reason, a review date
and an expiry date. Stale or expired exceptions fail the gate too, so the
allowlist cannot rot into a permanent waiver list.

Usage (CI mirrors these)::

    uv run --with pip-audit python scripts/check-dependency-audit.py --ecosystem pip
    python scripts/check-dependency-audit.py --ecosystem npm
    python scripts/check-dependency-audit.py --self-test

The exception process is documented in ``docs/dev/testing.md``
("Dependency-audit exceptions").
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWLIST = ROOT / "security" / "dependency-audit-allowlist.json"
SEVERITY_RANK = {"info": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}
EXCEPTION_KEYS = {"id", "package", "reason", "reviewed", "expires"}


class AllowlistError(ValueError):
    """Raised when the allowlist file itself is malformed."""


def _parse_date(value: Any, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AllowlistError(f"{where}: {value!r} is not an ISO date (YYYY-MM-DD)") from exc


def load_allowlist(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load and validate the reviewed exception file.

    Args:
        path: JSON allowlist path.

    Returns:
        The allowlist split into the ``pip``, ``pipUnresolved`` and ``npm`` lists.

    Raises:
        AllowlistError: When the file is missing, not JSON, or an entry is
            incomplete (a waiver without a reason/review/expiry is not a waiver).
    """
    if not path.exists():
        raise AllowlistError(f"allowlist not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise AllowlistError(f"{path}: expected a JSON object")
    unknown = set(raw) - {"$comment", "pip", "pipUnresolved", "npm"}
    if unknown:
        raise AllowlistError(f"{path}: unknown sections {sorted(unknown)}")
    allowlist: dict[str, list[dict[str, Any]]] = {}
    for section in ("pip", "pipUnresolved", "npm"):
        entries = raw.get(section, [])
        if not isinstance(entries, list):
            raise AllowlistError(f"{path}: {section} must be a list")
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            where = f"{path}: {section}[{index}]"
            if not isinstance(entry, dict):
                raise AllowlistError(f"{where}: expected an object")
            required = {"package", "reason"} if section == "pipUnresolved" else EXCEPTION_KEYS
            missing = required - set(entry)
            if missing:
                raise AllowlistError(f"{where}: missing {sorted(missing)}")
            extra = set(entry) - required
            if extra:
                raise AllowlistError(f"{where}: unknown keys {sorted(extra)}")
            if not str(entry["reason"]).strip():
                raise AllowlistError(f"{where}: reason must not be empty")
            if section != "pipUnresolved":
                _parse_date(entry["reviewed"], f"{where}.reviewed")
                _parse_date(entry["expires"], f"{where}.expires")
            key = str(entry["id"] if "id" in entry else entry["package"])
            if key in seen:
                raise AllowlistError(f"{where}: duplicate entry {key}")
            seen.add(key)
        allowlist[section] = entries
    return allowlist


def _active_exceptions(
    entries: list[dict[str, Any]], today: date, blocking: list[str]
) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for entry in entries:
        identifier = str(entry.get("id", entry.get("package")))
        if _parse_date(entry["expires"], identifier) < today:
            blocking.append(
                f"allowlist exception expired: {identifier} ({entry['package']}) "
                f"on {entry['expires']} — re-review it in "
                f"security/dependency-audit-allowlist.json"
            )
            continue
        active[identifier] = entry
    return active


def pip_findings(
    report: dict[str, Any],
    allowlist: dict[str, list[dict[str, Any]]],
    today: date,
) -> tuple[list[str], set[str], list[str]]:
    """Evaluate a ``pip-audit --format json`` report.

    Args:
        report: parsed pip-audit JSON.
        allowlist: validated allowlist sections.
        today: date used for expiry checks.

    Returns:
        ``(blocking findings, matched allowlist ids, informational notes)``.
    """
    blocking: list[str] = []
    notes: list[str] = []
    active = _active_exceptions(allowlist.get("pip", []), today, blocking)
    unresolved = {str(e["package"]): e for e in allowlist.get("pipUnresolved", [])}
    matched: set[str] = set()
    for dependency in report.get("dependencies", []):
        name = str(dependency.get("name"))
        skip_reason = dependency.get("skip_reason")
        if skip_reason:
            if name not in unresolved:
                blocking.append(
                    f"unauditable dependency {name} ({skip_reason}) — declare it in "
                    f"security/dependency-audit-allowlist.json#pipUnresolved with a reason"
                )
            else:
                notes.append(f"skipped (allowlisted): {name} — {skip_reason}")
            continue
        for vuln in dependency.get("vulns", []):
            identifier = str(vuln.get("id"))
            ids = [identifier, *(str(a) for a in vuln.get("aliases", []))]
            entry = next((active[i] for i in ids if i in active), None)
            if entry is None:
                blocking.append(
                    f"vulnerable dependency: {name} {dependency.get('version')} — {identifier} "
                    f"(fix: {', '.join(vuln.get('fix_versions', [])) or 'none'})"
                )
                continue
            matched.update(i for i in ids if i in active)
            if entry["package"] != name:
                notes.append(f"{identifier}: package changed {entry['package']} -> {name}")
    for identifier in active:
        if identifier not in matched:
            blocking.append(
                f"stale allowlist exception: {identifier} is no longer reported — "
                f"remove it from security/dependency-audit-allowlist.json"
            )
    return blocking, matched, notes


def npm_findings(
    report: dict[str, Any],
    allowlist: dict[str, list[dict[str, Any]]],
    today: date,
    min_severity: str = "high",
) -> tuple[list[str], set[str], list[str]]:
    """Evaluate an ``npm audit --json`` report.

    Args:
        report: parsed npm audit JSON (auditReportVersion 2).
        allowlist: validated allowlist sections.
        today: date used for expiry checks.
        min_severity: severity floor that blocks.

    Returns:
        ``(blocking findings, matched allowlist ids, informational notes)``.
    """
    blocking: list[str] = []
    notes: list[str] = []
    active = _active_exceptions(allowlist.get("npm", []), today, blocking)
    floor = SEVERITY_RANK[min_severity]
    matched: set[str] = set()
    reported: dict[str, tuple[str, str, str]] = {}
    for package, info in report.get("vulnerabilities", {}).items():
        for via in info.get("via", []):
            if not isinstance(via, dict):
                continue
            url = str(via.get("url", ""))
            identifier = url.rsplit("/", 1)[-1] if url else str(via.get("source", ""))
            severity = str(via.get("severity", info.get("severity", "info")))
            reported[identifier] = (package, severity, str(via.get("title", "")))
    for identifier, (package, severity, title) in sorted(reported.items()):
        if SEVERITY_RANK.get(severity, 0) < floor:
            notes.append(f"below {min_severity}: {identifier} ({package}, {severity})")
            continue
        entry = active.get(identifier)
        if entry is None:
            blocking.append(
                f"vulnerable dependency: {package} — {identifier} ({severity}) {title}"
            )
            continue
        matched.add(identifier)
        if entry["package"] != package:
            notes.append(f"{identifier}: package changed {entry['package']} -> {package}")
    for identifier in active:
        if identifier not in matched:
            blocking.append(
                f"stale allowlist exception: {identifier} is no longer reported — "
                f"remove it from security/dependency-audit-allowlist.json"
            )
    return blocking, matched, notes


def _run(cmd: list[str], cwd: Path) -> dict[str, Any]:
    print(f"$ {' '.join(cmd)} (cwd={cwd})", flush=True)
    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    stdout = completed.stdout.strip()
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        detail = (completed.stderr or stdout or "<no output>").strip()
        raise SystemExit(f"could not parse audit JSON ({exc}):\n{detail}") from exc


def _pip_command() -> list[str]:
    executable = shutil.which("pip-audit")
    if executable:
        return [executable, "--format", "json", "--progress-spinner", "off"]
    return [sys.executable, "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"]


def _self_test() -> int:
    today = date(2026, 10, 21)

    def pip_allow(*ids: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "pip": [
                {
                    "id": identifier,
                    "package": "demo",
                    "reason": "not reachable",
                    "reviewed": "2026-10-01",
                    "expires": "2027-01-01",
                }
                for identifier in ids
            ],
            "pipUnresolved": [{"package": "localpkg", "reason": "workspace source"}],
            "npm": [],
        }

    def npm_allow(*ids: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "pip": [],
            "pipUnresolved": [],
            "npm": [
                {
                    "id": identifier,
                    "package": "demo",
                    "reason": "dev tooling only",
                    "reviewed": "2026-10-01",
                    "expires": "2027-01-01",
                }
                for identifier in ids
            ],
        }

    def pip_report(name: str, *vulns: str, skip: str | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": name, "version": "1", "vulns": []}
        entry["vulns"] = [{"id": vuln} for vuln in vulns]
        if skip:
            entry["skip_reason"] = skip
        return {"dependencies": [entry]}

    def npm_report(package: str, identifier: str, severity: str) -> dict[str, Any]:
        url = f"https://github.com/advisories/{identifier}"
        via = {"url": url, "severity": severity, "title": "t"}
        return {"vulnerabilities": {package: {"severity": severity, "via": [via]}}}

    cases: list[tuple[str, bool, list[str]]] = []

    clean = pip_findings(pip_report("demo"), pip_allow(), today)
    cases.append(("pip clean", not clean[0], clean[0]))

    allowed = pip_findings(pip_report("demo", "CVE-2026-1"), pip_allow("CVE-2026-1"), today)
    cases.append(("pip allowlisted vuln passes", not allowed[0], allowed[0]))

    blocked = pip_findings(pip_report("demo", "CVE-2026-9"), pip_allow(), today)
    cases.append(("pip unlisted vuln blocks", bool(blocked[0]), []))

    skip = pip_findings(pip_report("mystery", skip="not on PyPI"), pip_allow(), today)
    cases.append(("pip unauditable dependency blocks", bool(skip[0]), []))

    local = pip_findings(pip_report("localpkg", skip="not on PyPI"), pip_allow(), today)
    cases.append(("pip allowlisted unresolved passes", not local[0], local[0]))

    stale = pip_findings(pip_report("demo"), pip_allow("CVE-2026-1"), today)
    cases.append(("pip stale exception blocks", bool(stale[0]), []))

    expired_allow = pip_allow("CVE-2026-1")
    expired_allow["pip"][0]["expires"] = "2026-01-01"
    expired = pip_findings(pip_report("demo", "CVE-2026-1"), expired_allow, today)
    cases.append(("expired exception blocks", len(expired[0]) == 2, expired[0]))

    npm_allowed = npm_findings(
        npm_report("demo", "GHSA-demo-demo-demo", "high"),
        npm_allow("GHSA-demo-demo-demo"),
        today,
    )
    cases.append(("npm allowlisted advisory passes", not npm_allowed[0], npm_allowed[0]))

    npm_low = npm_findings(
        npm_report("demo2", "GHSA-low0-low0-low0", "low"), npm_allow(), today
    )
    cases.append(("npm low severity does not block", not npm_low[0], npm_low[0]))

    npm_blocked = npm_findings(
        npm_report("demo3", "GHSA-crit-crit-crit", "critical"), npm_allow(), today
    )
    cases.append(("npm unlisted high blocks", bool(npm_blocked[0]), []))

    failures = [(name, why) for name, ok, why in cases if not ok]
    for name, ok, _ in cases:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        for name, why in failures:
            print(f"self-test failure: {name}: {why}", file=sys.stderr)
        return 1
    print(f"self-test: {len(cases)} cases passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the audit gate.

    Args:
        argv: CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 = all findings allowlisted and reviewed).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ecosystem", choices=("pip", "npm", "all"), default="all")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--min-severity", choices=tuple(SEVERITY_RANK), default="high")
    parser.add_argument("--report", type=Path, help="evaluate a saved audit JSON report")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        allowlist = load_allowlist(args.allowlist)
    except AllowlistError as exc:
        print(f"dependency-audit: {exc}", file=sys.stderr)
        return 1
    today = date.today()
    ecosystems = ("pip", "npm") if args.ecosystem == "all" else (args.ecosystem,)
    failed = False
    for ecosystem in ecosystems:
        if args.report is not None:
            report = json.loads(args.report.read_text(encoding="utf-8"))
        elif ecosystem == "pip":
            report = _run(_pip_command(), ROOT / "backend")
        else:
            report = _run(["npm", "audit", "--json"], ROOT / "frontend")
        if ecosystem == "pip":
            blocking, _matched, notes = pip_findings(report, allowlist, today)
        else:
            blocking, _matched, notes = npm_findings(report, allowlist, today, args.min_severity)
        for note in notes:
            print(f"  note: {note}")
        if blocking:
            failed = True
            for finding in blocking:
                print(f"  BLOCKED [{ecosystem}] {finding}", file=sys.stderr)
        else:
            print(f"{ecosystem} audit: clean (only reviewed exceptions, none expired)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
