"""Storage adapters (plan 50): the family vector-retrieval seam.

``vector_contract`` is the vendored family contract (ADR-0031/ADR-0051,
byte-identical to ``the family vector contract`` — never edit it
here); ``vector_schema`` owns the physical-index naming and the Alembic
autogenerate exemption; ``vector_provisioning`` creates a space's physical
index off the request path; ``vector_backends`` holds the PostgreSQL,
sqlite-vec and linear SQL adapters plus the one-per-process factory; and
``vector_store`` is the metadata-owning service.
"""
