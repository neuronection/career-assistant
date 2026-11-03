"""Storage adapters (plan 50): the family vector-retrieval seam.

``vector_contract`` is the vendored family contract (ADR-0031/ADR-0051,
byte-identical to ``dev/contracts/vector_contract.py`` — never edit it
here); ``vector_backends`` holds the app-side SQL adapters and the
one-per-process backend factory.
"""
