"""Physical vector-index naming and the Alembic autogenerate exemption
(plan 50 §3.4, P1b).

The ``vec_*`` tables and the sqlite-vec ``vector_entry_ids`` rowid map are
extension-managed objects: the provisioning seam owns their DDL, not the ORM
metadata. Alembic autogenerate therefore has to ignore them, or a live/dev
database would emit a ``RemoveTable`` on every comparison.

The naming rule is also the security boundary for the dynamic SQL the
backends issue: only ``vec_`` + eight lowercase hex characters is accepted,
so a table name can never carry an injected predicate.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

INDEX_TABLE_RE = re.compile(r"^vec_[0-9a-f]{8}$")
VECTOR_ENTRY_IDS_TABLE = "vector_entry_ids"
_VECTOR_INDEX_RE = re.compile(r"^ix_vec_[0-9a-f]{8}_hnsw$")


def index_table_name(space_id: str | uuid.UUID) -> str:
    """Derive the physical index table name from the space UUID."""
    return f"vec_{uuid.UUID(str(space_id)).hex[:8]}"


def validate_index_table(name: str) -> str:
    """Refuse anything that is not exactly ``vec_<8 lowercase hex>``."""
    if not isinstance(name, str) or INDEX_TABLE_RE.fullmatch(name) is None:
        raise ValueError(f"invalid vector index table name: {name!r}")
    return name


def is_extension_managed_table(name: str | None) -> bool:
    """True for the physical index tables and the sqlite-vec rowid map."""
    if not name:
        return False
    return name == VECTOR_ENTRY_IDS_TABLE or INDEX_TABLE_RE.fullmatch(name) is not None


def include_object(
    _object: Any,
    name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: Any,
) -> bool:
    """Alembic ``include_object`` hook: hide extension-managed vector objects."""
    if type_ == "table":
        return not is_extension_managed_table(name)
    if type_ == "index":
        return not (name is not None and _VECTOR_INDEX_RE.fullmatch(name) is not None)
    return True
