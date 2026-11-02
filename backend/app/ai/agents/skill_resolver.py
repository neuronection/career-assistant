"""Pass-2 skill resolution verdicts (plan 153, slice 2).

Pass-1 extraction emits taxonomy-blind raw labels; the deterministic
candidate matcher (``app.services.postings.skill_candidates``) proposes
the existing skills each label might denote. One batched structured call
adjudicates ``match_key | new`` per label over its own candidates. The
offline teacher of the taxonomy — never on a query path. Unconfigured or
failing AI surfaces as ``None``/``AINotConfiguredError`` and the caller
falls back to deterministic ``new`` proposals.

Verdict field types are transport-only: one malformed verdict must never
fail (and re-bill) the whole batch, so semantic validation happens per
verdict in :func:`apply_label_verdicts` (the ``apply_verdicts`` pattern
of the relation teacher) and a returned key is never trusted beyond the
offering candidate set (the ``target_resolver`` contract) — it degrades
that label to ``new`` instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.core.errors import AINotConfiguredError
from app.models.enums import AITaskType

MAX_LABELS_PER_CALL = 40

_SYSTEM = (
    "You are the pass-2 resolver of a two-pass skill extraction pipeline "
    "on a student career platform. Pass 1 extracted raw skill labels from "
    "a job posting verbatim; a deterministic matcher already proposed, "
    "for each label, the existing catalog skills it might denote. You "
    "judge each raw label against ITS OWN candidates only, and answer "
    "for EVERY label exactly once.\n"
    "Each label carries label_ref, raw_label and its ranked candidates "
    "with key, label, aliases, score and signal. A label's candidates "
    "are never candidates of another label.\n"
    "Decision rules:\n"
    "- The raw label denotes the SAME skill as a candidate: answer that "
    "candidate's key as match_key, copied EXACTLY as offered (ml / "
    "machine-learning with alias ml is a match).\n"
    "- The label is distinct-but-related to every candidate (typescript "
    "vs javascript, c vs c++), or you are unsure, or no candidate fits: "
    "answer new.\n"
    "- NEVER invent keys: a match_key that was not offered with that "
    "label is a wrong answer, and a key from another label's candidates "
    "is never copied.\n"
    "Each verdict: label_ref copied exactly, match_key (empty string "
    "when new), new (true when match_key is empty), confidence 0.0-1.0, "
    "rationale one sentence (max 500 chars). Set bounded true only when "
    "you could not answer every offered label."
)


class SkillLabelVerdict(BaseModel):
    """The model's answer for one raw label.

    Transport-only field types (``match_key``/``new``/``confidence``
    carry no key-universe or bounds constraints): semantic validation
    happens per verdict in :func:`apply_label_verdicts` so one malformed
    answer is dropped, never a whole batch.
    """

    label_ref: str
    match_key: str = ""
    new: bool = False
    confidence: float
    rationale: str


class SkillResolution(BaseModel):
    """Bounded verdict list — one entry per label in the batch."""

    verdicts: list[SkillLabelVerdict] = Field(max_length=MAX_LABELS_PER_CALL)
    bounded: bool = False


def _mock_norm(value: str) -> str:
    return " ".join((value or "").lower().replace("-", " ").replace("_", " ").split())


_MOCK_EXACT_CONFIDENCE = 0.9
_MOCK_TOP_CANDIDATE_BAR = 0.5
_MOCK_TOP_CONFIDENCE = 0.6
_MOCK_NEW_CONFIDENCE = 0.5


def _mock_skill_resolution(_schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    verdicts = []
    for label in ctx.get("labels", []):
        raw = _mock_norm(str(label.get("raw_label") or ""))
        candidates = label.get("candidates") or []
        chosen = None
        confidence = _MOCK_NEW_CONFIDENCE
        for candidate in candidates:
            texts = [str(candidate.get("key") or ""), str(candidate.get("label") or "")]
            texts.extend(str(alias) for alias in candidate.get("aliases") or [])
            if raw and raw in {_mock_norm(text) for text in texts if text}:
                chosen = candidate
                confidence = _MOCK_EXACT_CONFIDENCE
                break
        if chosen is None and candidates:
            top = candidates[0]
            try:
                score = float(top.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score >= _MOCK_TOP_CANDIDATE_BAR:
                chosen = top
                confidence = _MOCK_TOP_CONFIDENCE
        if chosen is None:
            verdicts.append(
                {
                    "label_ref": label.get("label_ref", ""),
                    "match_key": "",
                    "new": True,
                    "confidence": _MOCK_NEW_CONFIDENCE,
                    "rationale": (
                        "Deterministic mock verdict: no candidate matches the raw label."
                    ),
                }
            )
        else:
            verdicts.append(
                {
                    "label_ref": label.get("label_ref", ""),
                    "match_key": str(chosen.get("key") or ""),
                    "new": False,
                    "confidence": confidence,
                    "rationale": (
                        "Deterministic mock verdict: the offered candidate matches the raw label."
                    ),
                }
            )
    return {"verdicts": verdicts, "bounded": False}


register_mock_fixture(AITaskType.POSTING_SKILL_RESOLVE, _mock_skill_resolution)


def build_labels_prompt(labels: list[dict]) -> str:
    """Serialize one batch of raw-label candidate contexts for the model."""
    return context_json({"labels": labels})


def apply_label_verdicts(labels: list[dict], resolution: SkillResolution) -> SkillResolution:
    """Semantic validation over the transport reply, per verdict.

    Mirrors the relation teacher's ``apply_verdicts``: one malformed
    verdict never fails the batch. Verdicts for unknown label_refs go
    missing (dropped), a duplicated label_ref keeps its first answer
    even when malformed, and a verdict whose confidence sits outside
    0-1 is unusable. Every offered label is answered exactly once in
    the result: unusable answers, and answers whose match_key is not
    among that label's own offered candidate keys (never trusted, the
    ``target_resolver`` contract), degrade to ``new``. ``bounded``
    reports whether any label lacked a usable model verdict.
    """
    offered: dict[str, set[str]] = {}
    for label in labels:
        ref = str(label.get("label_ref") or "")
        if not ref:
            continue
        keys = {str(candidate.get("key") or "") for candidate in label.get("candidates") or []}
        keys.discard("")
        offered[ref] = keys
    first: dict[str, SkillLabelVerdict] = {}
    for verdict in resolution.verdicts:
        if verdict.label_ref in offered and verdict.label_ref not in first:
            first[verdict.label_ref] = verdict
    verdicts: list[SkillLabelVerdict] = []
    bounded = resolution.bounded
    for ref, keys in offered.items():
        answer = first.get(ref)
        if answer is None or not 0.0 <= answer.confidence <= 1.0:
            verdicts.append(
                SkillLabelVerdict(
                    label_ref=ref, match_key="", new=True, confidence=0.0, rationale=""
                )
            )
            bounded = True
            continue
        match_key = answer.match_key if answer.match_key in keys else ""
        verdicts.append(
            SkillLabelVerdict(
                label_ref=ref,
                match_key=match_key,
                new=not match_key,
                confidence=answer.confidence,
                rationale=answer.rationale,
            )
        )
    return SkillResolution(verdicts=verdicts, bounded=bounded)


async def resolve_skills(
    db: AsyncSession,
    labels: list[dict],
    *,
    user_id=None,
    run: RunRef | None = None,
) -> SkillResolution | None:
    """One batched pass-2 call: raw labels → ``match_key | new`` verdicts.

    ``labels`` entries carry label_ref, raw_label and the candidate list
    the deterministic matcher proposed (``{key, label, aliases, score,
    signal}``); exactly one audited gateway call covers the whole batch,
    with ``run`` pinning the audit row to the background job serving it.
    The reply is adjudicated per verdict (:func:`apply_label_verdicts`),
    so the result answers every offered label exactly once and never
    carries a key outside its label's candidate set. ``None`` = the
    provider failed — the caller falls back deterministically.

    Raises:
        AINotConfiguredError: when no provider is configured — the
            caller skips pass 2 deterministically.
    """
    if not labels:
        return SkillResolution(verdicts=[], bounded=False)
    try:
        resolution = await ainvoke_structured(
            db,
            AITaskType.POSTING_SKILL_RESOLVE,
            SkillResolution,
            _SYSTEM,
            build_labels_prompt(labels),
            user_id=user_id,
            run=run,
        )
    except AINotConfiguredError:
        raise
    except Exception:
        return None
    return apply_label_verdicts(labels, resolution)
