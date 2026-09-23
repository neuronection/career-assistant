"""Plan 110: fold the `:bullets` synth-pin slot into the single pin key.

One star per item: `cv_documents.context.synth_pins` keys
`"{source}:{id}:bullets"` merge into `"{source}:{id}"`:
- text pin only / bullets pin only → the key keeps that row id;
- both pinned to DIFFERENT rows → the bullets row's achievements merge
  INTO the text winner's payload (kept only when it had none) and the
  bullets row is archived with its former pin retired;
- both pinned to the same row → trivial one key.
Per-field winner semantics are preserved — never a blanket newest-wins.

Revision ID: 0041
Revises: 0040
"""

import json
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

BULLETS_SUFFIX = ":bullets"


def _as_dict(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _norm_id(value) -> str:
    """A dialect-neutral id key.

    Pin values are dashed UUID strings while SQLite stores `cv_synth_items.id`
    as hex — comparing raw text would never match there."""
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, AttributeError, TypeError):
        return str(value)


def _json_literal(conn, placeholder: str) -> str:
    """A JSON column write that works on both dialects.

    Postgres JSONB needs an explicit cast; SQLite stores JSON as TEXT and
    `CAST(x AS jsonb)` would fall back to NUMERIC affinity and write `0`
    (destroying the column) — never cast there.
    """
    if conn.dialect.name == "postgresql":
        return f"CAST({placeholder} AS jsonb)"
    return placeholder


def _plain_referenced_ids(parsed: list[tuple]) -> set[str]:
    """Every row id a PLAIN pin key points at across ALL of the user's CVs.

    A folded bullets row pinned plain on another CV must not be archived
    by this fold."""
    referenced: set[str] = set()
    for _cv_id, context in parsed:
        pins = context.get("synth_pins")
        if not isinstance(pins, dict):
            continue
        for key, value in pins.items():
            if value and not str(key).endswith(BULLETS_SUFFIX):
                referenced.add(str(value))
    return referenced


def upgrade() -> None:
    conn = op.get_bind()
    payload_expr = _json_literal(conn, ":p")
    context_expr = _json_literal(conn, ":c")

    item_rows = conn.execute(
        sa.text("SELECT id, payload FROM cv_synth_items")
    ).fetchall()
    items: dict[str, tuple] = {
        _norm_id(rid): (rid, _as_dict(payload) or {}) for rid, payload in item_rows
    }

    rows = conn.execute(
        sa.text(
            "SELECT id, context, user_id FROM cv_documents WHERE context IS NOT NULL"
        )
    ).fetchall()
    parsed = [
        (cv_id, context)
        for cv_id, raw, _user_id in rows
        if (context := _as_dict(raw)) is not None
    ]
    plain_referenced = _plain_referenced_ids(parsed)

    for cv_id, context in parsed:
        pins = context.get("synth_pins")
        if not isinstance(pins, dict) or not any(
            str(key).endswith(BULLETS_SUFFIX) for key in pins
        ):
            continue

        folded: dict[str, dict] = {}
        new_pins: dict[str, str] = {}
        for key, value in pins.items():
            if value and str(key).endswith(BULLETS_SUFFIX):
                ref_key = str(key)[: -len(BULLETS_SUFFIX)]
                entry = folded.setdefault(ref_key, {"bullets": None, "text": None})
                entry["bullets"] = str(value)
        for key, value in pins.items():
            if str(key).endswith(BULLETS_SUFFIX):
                continue
            if value:
                new_pins[key] = str(value)
            if value and key in folded:
                folded[key]["text"] = str(value)

        for ref_key, pairs in folded.items():
            bullets_id = pairs["bullets"]
            text_id = pairs["text"]
            if text_id is None:
                # Bullets-only star keeps its row on the single key.
                new_pins[ref_key] = bullets_id
                continue
            if bullets_id is None or bullets_id == text_id:
                continue
            text_entry = items.get(_norm_id(text_id))
            bullets_entry = items.get(_norm_id(bullets_id))
            if text_entry is None and bullets_entry is None:
                # Both rows gone — the pin is dead; drop it, never dangle.
                new_pins.pop(ref_key, None)
                continue
            if text_entry is None:
                new_pins[ref_key] = bullets_id
                continue
            if bullets_entry is None:
                new_pins[ref_key] = text_id
                continue
            text_raw_id, text_payload = text_entry
            bullets_raw_id, bullets_payload = bullets_entry
            if not text_payload.get("achievements") and bullets_payload.get(
                "achievements"
            ):
                text_payload["achievements"] = bullets_payload["achievements"]
                conn.execute(
                    sa.text(
                        f"UPDATE cv_synth_items SET payload = {payload_expr} "
                        "WHERE id = :rid"
                    ),
                    {"p": json.dumps(text_payload), "rid": text_raw_id},
                )
            new_pins[ref_key] = text_id
            if bullets_id not in plain_referenced:
                conn.execute(
                    sa.text(
                        "UPDATE cv_synth_items SET status = 'archived' "
                        "WHERE id = :rid"
                    ),
                    {"rid": bullets_raw_id},
                )

        context["synth_pins"] = new_pins
        conn.execute(
            sa.text(
                f"UPDATE cv_documents SET context = {context_expr} WHERE id = :cid"
            ),
            {"c": json.dumps(context), "cid": cv_id},
        )


def downgrade() -> None:
    # The fold is lossy by design: a merged achievement field cannot be
    # split back into its source rows, and the retired duplicate row's
    # former star is not recoverable. Nothing to reverse.
    pass
