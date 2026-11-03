"""Vector-retrieval vocabularies (plan 50 P1).

The space lifecycle, degradation reasons and view vocabulary live in the
vendored family contract (``app/storage/vector_contract.py``); this module
adds only the app-side scope vocabulary the contract deliberately leaves
opaque.
"""

from enum import StrEnum


class VectorScopeType(StrEnum):
    """Ownership axis of a vector document (plan 50 §3.2).

    ``tenant`` covers the web multi-user instance, ``user`` a single
    account's private documents, and ``global`` shared catalog rows.
    A document has exactly one axis; ``profile_id`` narrows within it and
    is never a second ownership axis (plan 16 §5.6).
    """

    USER = "user"
    TENANT = "tenant"
    GLOBAL = "global"
