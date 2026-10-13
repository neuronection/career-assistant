"""Plan 26 Phase 4 / plan 100 batch A — BYOK uniform realignment (schema).

One revision carrying the whole §15 vocabulary + slot-default wave:

- ``ai_providers.preset_key`` — the §15 preset-adoption stamp (setup
  adopts matching manual rows and stamps them; NULL = custom);
- ``ai_models.decision_transport`` — the ADR-0032 decision seam
  (``systemone``; set exactly for decision-capable models);
- capability vocabulary split: stored ``caps`` remap ``audio → stt``
  exactly once (career's ``audio`` was STT-only in practice — dictation;
  no ``tts`` rows are invented because career ships no TTS task yet);
- the ``default`` pseudo-task dies: its assignment rows remap to the
  ``text`` capability slot (the slot-default design replaces the global
  fallback; a same-scope ``text`` row wins and the duplicate is dropped).

**No legacy/back-compat** (owner ruling plan 26 §13.8 — pre-release, no
users): the downgrade drops the slot-vocabulary assignment rows
(``text``/``vision``/``stt``/``tts`` — rows that cannot exist on the
previous schema's vocabulary) and remaps ``stt → audio``; it does not
resurrect the ``default`` pseudo-task.

Revision ID: 0045
Revises: 0044
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
_UUID = sa.Uuid()

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

SLOT_TASK_TYPES = ("text", "vision", "stt", "tts")

_ai_models = sa.table(
    "ai_models",
    sa.column("id", _UUID),
    sa.column("caps", _JSON),
)

_ai_task_assignments = sa.table(
    "ai_task_assignments",
    sa.column("id", _UUID),
    sa.column("task_type", sa.String),
)


def _load_caps(raw: object) -> list[str] | None:
    if isinstance(raw, list):
        return [cap for cap in raw if isinstance(cap, str)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        if isinstance(parsed, list):
            return [cap for cap in parsed if isinstance(cap, str)]
    return None


def _rewrite_caps(mapping: dict[str, tuple[str, ...]]) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, caps FROM ai_models")).fetchall()
    for row_id, raw_caps in rows:
        caps = _load_caps(raw_caps)
        if caps is None:
            continue
        updated: list[str] = []
        for cap in caps:
            replacement = mapping.get(cap, (cap,))
            updated.extend(replacement)
        deduped: list[str] = []
        for cap in updated:
            if cap not in deduped:
                deduped.append(cap)
        if deduped != caps:
            op.execute(_ai_models.update().where(_ai_models.c.id == row_id).values(caps=deduped))


def _slot_occupied(bind, scope: str, user_id: str | None) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM ai_task_assignments "
            "WHERE task_type = 'text' AND scope = :scope "
            "AND (user_id = :user OR (user_id IS NULL AND :user IS NULL))"
        ),
        {"scope": scope, "user": user_id},
    ).first()
    return row is not None


def upgrade() -> None:
    op.add_column(
        "ai_providers",
        sa.Column("preset_key", sa.String(length=40), nullable=True),
    )
    op.create_index("ix_ai_providers_preset_key", "ai_providers", ["preset_key"])
    op.add_column(
        "ai_models",
        sa.Column("decision_transport", sa.String(length=20), nullable=True),
    )
    _rewrite_caps({"audio": ("stt",)})

    bind = op.get_bind()
    default_rows = bind.execute(
        sa.text("SELECT id, scope, user_id FROM ai_task_assignments WHERE task_type = 'default'")
    ).fetchall()
    for row_id, scope, user_id in default_rows:
        if _slot_occupied(bind, scope, user_id):
            bind.execute(
                sa.text("DELETE FROM ai_task_assignments WHERE id = :id"),
                {"id": row_id},
            )
        else:
            bind.execute(
                sa.text("UPDATE ai_task_assignments SET task_type = 'text' WHERE id = :id"),
                {"id": row_id},
            )


def downgrade() -> None:
    op.execute(
        _ai_task_assignments.delete().where(_ai_task_assignments.c.task_type.in_(SLOT_TASK_TYPES))
    )
    _rewrite_caps({"stt": ("audio",)})
    op.drop_column("ai_models", "decision_transport")
    op.drop_index("ix_ai_providers_preset_key", table_name="ai_providers")
    op.drop_column("ai_providers", "preset_key")
