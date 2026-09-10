"""Embedding service: text composition, hash-deduped
storage and cosine retrieval over the ai_embeddings store.

Retrieval is Python-side cosine on every dialect — postings are
thousands, not millions, and one code path beats a dialect split. The
gateway's ``embed`` task carries the provider config (DB-only; the mock
provider synthesizes deterministic vectors for tests/dev).
"""

import hashlib
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding_model import AIEmbedding

# Which entity kinds embed; the store is open but the seed/recompute
# surfaces only serve these.
KIND_POSTING = "posting"
KIND_FAMILY = "family"
KIND_TEMPLATE = "template"
KIND_CHAT_SUMMARY = "chat_summary"


def _text_hash(text: str) -> str:
    normalized = " ".join((text or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine — no numpy dependency (desktop parity)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def compose_posting_text(posting) -> str:
    """The embedded surface of a posting: raw facts + validated extract
    (must-have skills with levels, responsibilities with time-splits)."""
    parts: list[str] = [posting.title, posting.org or ""]
    raw = posting.raw or {}
    for key in ("description", "text", "note"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value[:1200])
    extract = posting.extract or {}
    for skill in extract.get("skills") or []:
        label = skill.get("raw_label") or skill.get("skill_key")
        if label:
            priority = skill.get("priority") or ""
            level = skill.get("required_level")
            parts.append(f"skill: {label} {priority} {level or ''}".strip())
    for resp in extract.get("responsibilities") or []:
        text = resp.get("text")
        if text:
            share = f" ({resp['time_pct']}%)" if resp.get("time_pct") else ""
            parts.append(f"responsibility: {text}{share}")
    return "\n".join(part for part in parts if part)


class EmbeddingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_embedding(
        self,
        entity_kind: str,
        entity_id: uuid.UUID,
        text: str,
        *,
        vector: Optional[list[float]] = None,
    ) -> tuple[AIEmbedding, bool]:
        """Store (or refresh) one embedding; returns (row, embedded?).

        ``embedded`` is False when the stored row was already current
        (content-hash dedupe — no gateway spend for unchanged text).
        """
        from app.ai.gateway import embed_texts

        text_hash = _text_hash(text)
        row = (
            (
                await self.db.execute(
                    select(AIEmbedding).where(
                        AIEmbedding.entity_kind == entity_kind,
                        AIEmbedding.entity_id == entity_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None and row.content_hash == text_hash:
            return row, False
        if vector is None:
            vector = (await embed_texts(self.db, [text]))[0]
        if row is None:
            row = AIEmbedding(entity_kind=entity_kind, entity_id=entity_id)
            self.db.add(row)
        row.content_hash = text_hash
        row.dim = len(vector)
        row.vector = vector
        await self.db.commit()
        return row, True

    async def recompute_postings(self, limit: int = 50) -> dict:
        """Embed stale/un-embedded postings (title + raw + extract)."""
        from app.models.posting_model import JobPosting

        rows = (
            (
                await self.db.execute(
                    select(JobPosting)
                    .outerjoin(AIEmbedding, AIEmbedding.entity_id == JobPosting.id)
                    .where(AIEmbedding.id.is_(None))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        embedded = 0
        for posting in rows:
            text = compose_posting_text(posting)
            if not text.strip():
                continue
            _, did = await self.upsert_embedding(KIND_POSTING, posting.id, text)
            embedded += 1 if did else 0
        return {"candidates": len(rows), "embedded": embedded}

    async def search_similar(
        self,
        query: str,
        *,
        kind: Optional[str] = KIND_POSTING,
        limit: int = 20,
    ) -> list[dict]:
        """Cosine ranking over the stored vectors (semantic SIGNAL only —
        callers must keep SQL hard filters upstream)."""
        from app.ai.gateway import embed_texts

        if not query.strip():
            return []
        query_vector = (await embed_texts(self.db, [query]))[0]
        query_dim = len(query_vector)
        stmt = select(AIEmbedding).where(AIEmbedding.dim == query_dim)
        if kind is not None:
            stmt = stmt.where(AIEmbedding.entity_kind == kind)
        rows = (await self.db.execute(stmt)).scalars().all()
        scored = [
            {
                "entity_kind": row.entity_kind,
                "entity_id": str(row.entity_id),
                "score": round(cosine(query_vector, row.vector), 4),
            }
            for row in rows
        ]
        scored.sort(key=lambda item: -item["score"])
        return scored[:limit]

    async def status(self) -> list[dict]:
        rows = await self.db.execute(
            select(
                AIEmbedding.entity_kind,
                AIEmbedding.dim,
                AIEmbedding.content_hash,
            )
        )
        buckets: dict[tuple[str, int], dict] = {}
        for kind, dim, _hash in rows.all():
            bucket = buckets.setdefault(
                (kind, dim), {"entity_kind": kind, "dim": dim, "count": 0}
            )
            bucket["count"] += 1
        return sorted(buckets.values(), key=lambda b: b["entity_kind"])
