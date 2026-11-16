"""Fixture integrity for the plan-210 score-v3 calibration construction.

The synthetic corpus may be re-tuned only by changing filler weights. This
test pins the 164 pre-existing case objects (including the semantic oracle and
posting status) and the 123 pre-existing jobs' non-filler fields to committed
manifests in ``posting_mapping_fixture_delta.json``; a future edit that changes
a case meaning or a job's skills/title/family/status/description fails here
instead of silently moving a case across a score boundary.
"""

from __future__ import annotations

import hashlib
import json

from tests.posting_mapping_calibration import FIXTURE_DELTA_PATH, FIXTURE_PATH


def _digest(rows: list[dict], fields: list[str]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _case_digest(cases: list[dict], fields: list[str], case_ids: list[str]) -> str:
    by_id = {case["id"]: case for case in cases}
    rows = [{field: by_id[case_id].get(field) for field in fields} for case_id in sorted(case_ids)]
    return _digest(rows, fields)


def _job_digest(jobs: list[dict], fields: list[str], job_codes: list[str]) -> str:
    by_code = {job["code"]: job for job in jobs}
    rows = [{field: by_code[code].get(field) for field in fields} for code in sorted(job_codes)]
    return _digest(rows, fields)


def test_every_preexisting_case_keeps_its_meaning():
    delta = json.loads(FIXTURE_DELTA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    manifest = delta["case_manifest"]

    assert manifest["organic_count"] == 164
    existing_ids = manifest["existing_case_ids"]
    assert len(existing_ids) == 164

    current_ids = {case["id"] for case in fixture["cases"]}
    missing = sorted(set(existing_ids) - current_ids)
    assert not missing, f"pre-existing case ids disappeared: {missing}"

    assert (
        _case_digest(
            fixture["cases"],
            manifest["case_fields"],
            existing_ids,
        )
        == manifest["canonical_sha256"]
    ), (
        "a pre-existing case object changed its id/title/description/skills/"
        "semantic oracle/expected job/family/outcome/posting status/manual/draft "
        "labels/skill_meta/kind/ambiguity; re-tuning is limited to filler weights"
    )


def test_every_preexisting_job_keeps_its_non_filler_fields():
    delta = json.loads(FIXTURE_DELTA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    manifest = delta["job_manifest"]

    assert manifest["organic_count"] == 123
    existing_codes = manifest["existing_job_codes"]
    assert len(existing_codes) == 123

    current_codes = {job["code"] for job in fixture["jobs"]}
    missing = sorted(set(existing_codes) - current_codes)
    assert not missing, f"pre-existing job codes disappeared: {missing}"

    assert (
        _job_digest(
            fixture["jobs"],
            manifest["job_fields"],
            existing_codes,
        )
        == manifest["canonical_sha256"]
    ), (
        "a pre-existing job changed its title/family/status/description/skills; "
        "re-tuning is limited to its fillers object"
    )
