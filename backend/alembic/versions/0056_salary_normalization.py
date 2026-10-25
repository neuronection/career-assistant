"""Plan 129 phase 2 — salary normalization on `job_postings`.

`salary_basis` (gross | net, NULL = the source never said) plus the
annualized range (`salary_normalized_min` / `_max`, the posted amounts
scaled to a year on their own basis — no FX, no gross/net conversion),
so a monthly and a yearly figure are comparable and the Explore salary
filter stops comparing hourly and yearly numbers unit-blind.

Data backfill: annualize every posting that carries an amount and a
known period — that restores comparability for existing rows. The basis
stays NULL for them: recovering gross/net means reading the posting's
free text (it survives in `posting.raw`), which is an AI re-extraction
(demand-path or admin-triggered), never a SQL guess. Model-first
(family-migration §1): mirrors `app.models.posting_model.JobPosting`.
``downgrade()`` drops the three columns.

Revision id: ``0056`` — chains onto the plan-129 phase-1 ``0055`` head.
"""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

# hour -> 2080 (40 h x 52), day -> 260 (5 x 52), week -> 52, month -> 12.
_FACTORS = {
    "hour": 2080,
    "day": 260,
    "week": 52,
    "month": 12,
    "year": 1,
}


def _annualized(column: str) -> str:
    branches = " ".join(
        f"WHEN salary_period = '{period}' THEN {column} * {factor}"
        for period, factor in _FACTORS.items()
    )
    return f"CASE {branches} ELSE NULL END"


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("salary_basis", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("salary_normalized_min", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("salary_normalized_max", sa.Numeric(12, 2), nullable=True),
    )
    with op.batch_alter_table("job_postings") as batch:
        batch.create_check_constraint(
            "salary_basis_allowed",
            "salary_basis IS NULL OR salary_basis IN ('gross', 'net')",
        )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE job_postings SET "
            f"salary_normalized_min = {_annualized('salary_min')}, "
            f"salary_normalized_max = {_annualized('salary_max')} "
            "WHERE salary_period IN ('hour', 'day', 'week', 'month', 'year') "
            "AND (salary_min IS NOT NULL OR salary_max IS NOT NULL)"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_constraint("salary_basis_allowed", type_="check")
    op.drop_column("job_postings", "salary_normalized_max")
    op.drop_column("job_postings", "salary_normalized_min")
    op.drop_column("job_postings", "salary_basis")
