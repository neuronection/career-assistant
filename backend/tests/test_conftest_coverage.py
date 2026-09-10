"""Guard: every SQLAlchemy model table must be covered by conftest.TABLES."""

from app.models import Base
from tests.conftest import TABLES


def test_tables_covers_all_models():
    model_tables = set(Base.metadata.tables)
    listed = set(TABLES)
    assert len(TABLES) == len(listed), "conftest.TABLES contains duplicates"
    missing = model_tables - listed
    extra = listed - model_tables
    assert not missing, f"tables missing from conftest.TABLES: {sorted(missing)}"
    assert not extra, f"conftest.TABLES lists unknown tables: {sorted(extra)}"


def test_tables_order_is_fk_safe():
    position = {name: i for i, name in enumerate(TABLES)}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            parent = fk.constraint.referred_table.name
            if parent == table.name:
                continue
            assert position[table.name] < position[parent], (
                f"'{table.name}' must be truncated/deleted before '{parent}' "
                "in conftest.TABLES (children first)"
            )
