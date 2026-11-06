"""HITL profile proposals package (plan 123.1).

Layout: ``kinds`` (registry), ``anchors`` (grounding + anchored edits),
``diff`` (card diffs), ``snapshots`` (full-entity snapshots), ``apply``
(dispatch to form services + loaders), ``preview`` (lazy before/after),
``telemetry`` (card serialization + fanout) and ``service`` (lifecycle
core). Import surface: ``app.services.profile_proposal_service``.
"""
