"""Plan 135 slice B — the gray-band arbiter and the suggestion lifecycle."""

import uuid

from sqlalchemy import func, select

from app.ai.agents.company_triage import PairVerdict, triage_pairs
from app.models.background_job_model import BackgroundJob
from app.models.experience_model import (
    Organization,
    OrganizationMatchExclusion,
    OrganizationMatchPair,
    OrganizationMergeSuggestion,
)
from app.models.posting_model import JobPosting
from app.services.catalog.company_names import name_key
from app.services.catalog.company_triage_service import (
    CompanyTriageService,
    enqueue_company_triage,
)
from app.services.catalog.organization_service import OrganizationService


def _pending_pair(
    db, org: Organization, label: str, *, domain: str | None = None, evidence: dict | None = None
) -> OrganizationMatchPair:
    pair = OrganizationMatchPair(
        label=label,
        label_key=name_key(label),
        org_id=org.id,
        evidence=evidence or {"domain": domain},
        status="pending",
    )
    db.add(pair)
    return pair


def _pending_posting(db, source, org_label: str, *, external_id: str) -> JobPosting:
    posting = JobPosting(
        source_id=source.id,
        external_id=external_id,
        content_hash=uuid.uuid4().hex,
        title="Ambiguous Employer Role",
        org=org_label,
        org_id=None,
        org_match={
            "layer": "initials",
            "score": 0.82,
            "matched_on": "initials",
            "state": "pending",
        },
    )
    db.add(posting)
    return posting


def _fake_verdicts(verdicts: list[dict]):
    async def _triage(_db, pairs):
        by_label = {pair["label"]: pair["pair_id"] for pair in pairs}
        return [
            PairVerdict(
                pair_id=by_label[entry["label"]],
                verdict=entry["verdict"],
                confidence=entry["confidence"],
                canonical_name=entry.get("canonical_name"),
            )
            for entry in verdicts
            if entry["label"] in by_label
        ]

    return _triage


async def test_mock_fixture_is_deterministic(db):
    verdicts = await triage_pairs(
        db,
        [
            {"pair_id": "pair-a", "label": "PG", "candidate_name": "Procter & Gamble"},
            {"pair_id": "pair-b", "label": "Acme", "candidate_name": "Acme Cloud"},
        ],
    )
    assert verdicts is not None
    assert [v.verdict for v in verdicts] == ["uncertain", "uncertain"]
    assert [v.pair_id for v in verdicts] == ["pair-a", "pair-b"]


async def test_same_with_corroboration_links_and_teaches(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Procter & Gamble", provenance={"source": "test"})
    org.domain = "pg.com"
    pair = _pending_pair(db, org, "P&G", domain="pg.com")
    posting = _pending_posting(db, source, "P&G", external_id="triage-same-1")
    await db.commit()

    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts([{"label": "P&G", "verdict": "same", "confidence": 0.97}]),
    )
    stats = await CompanyTriageService(db).run()
    assert stats["linked"] == 1

    await db.refresh(org)
    await db.refresh(pair)
    await db.refresh(posting)
    assert pair.status == "resolved" and pair.verdict == "same"
    assert posting.org_id == org.id and posting.org_match["state"] == "linked"
    aliases = await service.org_aliases(org.id)
    assert "P&G" in aliases
    assert org.status == "active", "a corroborated LLM same promotes (decision 8)"


async def test_low_confidence_same_asks_a_human(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Procter & Gamble", provenance={"source": "test"})
    pair = _pending_pair(db, org, "P&G", domain="pg.com")
    posting = _pending_posting(db, source, "P&G", external_id="triage-low-1")
    await db.commit()

    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts([{"label": "P&G", "verdict": "same", "confidence": 0.6}]),
    )
    stats = await CompanyTriageService(db).run()
    assert stats["suggested"] == 1

    await db.refresh(pair)
    assert pair.status == "resolved" and pair.confidence == 0.6
    suggestions = (await db.execute(select(OrganizationMergeSuggestion))).scalars().all()
    assert len(suggestions) == 1
    assert suggestions[0].label == "P&G"
    assert suggestions[0].status == "open"
    await db.refresh(posting)
    assert posting.org_id is not None and posting.org_id != org.id, (
        "the label's own (proposed) org takes the posting until a human decides"
    )


async def test_different_creates_and_excludes(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Global Solutions", provenance={"source": "test"})
    _pending_pair(db, org, "Global Solutions Group", domain="gsgroup.example")
    posting = _pending_posting(db, source, "Global Solutions Group", external_id="triage-diff-1")
    await db.commit()

    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts(
            [{"label": "Global Solutions Group", "verdict": "different", "confidence": 0.98}]
        ),
    )
    stats = await CompanyTriageService(db).run()
    assert stats["created"] == 1

    exclusion = (
        (
            await db.execute(
                select(OrganizationMatchExclusion).where(
                    OrganizationMatchExclusion.org_id == org.id
                )
            )
        )
        .scalars()
        .first()
    )
    assert exclusion is not None and exclusion.source == "llm"
    await db.refresh(posting)
    assert posting.org_id is not None and posting.org_id != org.id
    assert (posting.org_match or {})["state"] == "linked"


async def test_unconfigured_ai_falls_back_to_suggestions(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Acme Cloud", provenance={"source": "test"})
    _pending_pair(db, org, "Acme Cloud Ltd", domain=None)
    _pending_posting(db, source, "Acme Cloud Ltd", external_id="triage-unconf-1")
    await db.commit()

    async def _unconfigured(_db, _pairs):
        return None

    monkeypatch.setattr("app.services.catalog.company_triage_service.triage_pairs", _unconfigured)
    stats = await CompanyTriageService(db).run()
    assert stats["unconfigured"] is True
    assert stats["suggested"] == 1
    assert stats["remaining"] == 0, "pairs resolve into suggestions, never block ingest"
    suggestions = (await db.execute(select(OrganizationMergeSuggestion))).scalars().all()
    assert len(suggestions) == 1


async def test_dismiss_writes_the_pair_exclusion(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Acme Cloud", provenance={"source": "test"})
    _pending_pair(db, org, "Acme Cloud Ltd")
    await db.commit()
    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts([{"label": "Acme Cloud Ltd", "verdict": "uncertain", "confidence": 0.5}]),
    )
    await CompanyTriageService(db).run()
    suggestion = (await db.execute(select(OrganizationMergeSuggestion))).scalars().first()
    await CompanyTriageService(db).dismiss_suggestion(suggestion.id, decided_by="admin")

    await db.refresh(suggestion)
    assert suggestion.status == "dismissed"
    exclusion = (
        (
            await db.execute(
                select(OrganizationMatchExclusion).where(
                    OrganizationMatchExclusion.org_id == org.id,
                    OrganizationMatchExclusion.label_key == name_key("Acme Cloud Ltd"),
                )
            )
        )
        .scalars()
        .first()
    )
    assert exclusion is not None and exclusion.source == "dismiss"


async def test_accept_merges_the_label_org_into_the_candidate(db, source, monkeypatch):
    service = OrganizationService(db)
    org = await service.create_org("Acme Cloud", provenance={"source": "test"})
    _pending_pair(db, org, "Acme Cloud Ltd")
    _pending_posting(db, source, "Acme Cloud Ltd", external_id="triage-accept-1")
    await db.commit()
    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts([{"label": "Acme Cloud Ltd", "verdict": "uncertain", "confidence": 0.5}]),
    )
    await CompanyTriageService(db).run()
    suggestion = (await db.execute(select(OrganizationMergeSuggestion))).scalars().first()
    label_org_id = suggestion.org_a
    target = await CompanyTriageService(db).accept_suggestion(suggestion.id, decided_by="admin")
    assert target.id == org.id
    await db.refresh(suggestion)
    assert suggestion.status == "accepted"

    label_org = (
        await db.execute(select(Organization).where(Organization.id == label_org_id))
    ).scalar_one()
    assert label_org.status == "deprecated"
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.external_id == "triage-accept-1")))
        .scalars()
        .first()
    )
    assert posting.org_id == org.id, "accept re-points the postings"
    assert "Acme Cloud Ltd" in await service.org_aliases(org.id)


async def test_enqueue_depth_cap(db):
    assert await enqueue_company_triage(db) is False, "no pending pairs, no job"
    org = await OrganizationService(db).create_org("CapWorks", provenance={"source": "test"})
    _pending_pair(db, org, "Cap Works")
    await db.commit()

    assert await enqueue_company_triage(db) is True
    assert await enqueue_company_triage(db) is False, "one queued triage run at a time"
    queued = (
        await db.execute(
            select(func.count()).where(
                BackgroundJob.job_type == "company_triage",
                BackgroundJob.status == "queued",
            )
        )
    ).scalar_one()
    assert int(queued) == 1


async def test_promotion_policy(db, source):
    service = OrganizationService(db)
    solo = await service.create_org("Solo Works", provenance={"source": "test"})
    for _ in range(2):
        db.add(
            JobPosting(
                source_id=source.id,
                external_id=f"solo-{uuid.uuid4().hex[:6]}",
                content_hash=uuid.uuid4().hex,
                title="Role",
                org="Solo Works",
                org_id=solo.id,
            )
        )
    await db.commit()
    assert await service.maybe_promote(solo) is False, "one source is not enough"

    strong = await service.create_org("Strong Works", provenance={"source": "test"})
    await db.commit()
    assert await service.maybe_promote(strong, strong=True) is True
    assert strong.status == "active"
