"""fold the retired autopilot language toggle

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11

Plan 212 S1.4c removed `use_languages` from `ProfileUsage`
(`extra="forbid"`). Every pre-existing autopilot goal persisted the old
defaults, so a goal validated on read/run would now raise. This data
migration removes the retired key from `autopilot_goals.constraints.profile`
in place; the language itself stays in the planner context (it is no
longer a toggle).

Downgrade is a no-op: the pre-fold shape is not recorded (the retired
toggle is meaningless on the new engine).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GOALS = sa.table(
    "autopilot_goals",
    sa.column("id", sa.Uuid()),
    sa.column("constraints", app.models.base.StructuredJSON),
)


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_GOALS.c.id, _GOALS.c.constraints)).mappings()
    for row in rows:
        constraints = _as_dict(row["constraints"])
        profile = constraints.get("profile")
        if not isinstance(profile, dict) or "use_languages" not in profile:
            continue
        profile = dict(profile)
        profile.pop("use_languages", None)
        constraints = {**constraints, "profile": profile}
        bind.execute(
            sa.update(_GOALS).where(_GOALS.c.id == row["id"]).values(constraints=constraints)
        )


def downgrade() -> None:
    """No-op: the retired toggle has no meaningful value on the new engine."""
