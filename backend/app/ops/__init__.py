"""Server-ops entry points that run OUTSIDE the request path.

``provisioning`` is the owner-side provisioning seam executed by the
one-shot ``migrate`` mode (ADR-0062 §3, ADR-0064 §3): roles, extensions,
the Alembic chain, the checkpoint schema and the vector spaces — never
imported or run by a serving process.
"""
