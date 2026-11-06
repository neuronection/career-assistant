"""HITL profile proposals — stable public import surface (thin facade).

The implementation lives in ``app/services/proposals/`` (plan 123.1):
kinds, anchors, diff, snapshots, apply, preview, telemetry + the
lifecycle core in ``proposals/service.py``. This facade keeps the
historical import surface used by chat/cv/admin — the one permanent
facade the restructure plan allows.
"""

from app.services.proposals.anchors import (
    _as_achievement_entry as _as_achievement_entry,
)
from app.services.proposals.anchors import (
    _as_link_entry as _as_link_entry,
)
from app.services.proposals.anchors import (
    _as_skill_entry as _as_skill_entry,
)
from app.services.proposals.anchors import (
    _normalize_experience_payload as _normalize_experience_payload,
)
from app.services.proposals.anchors import (
    _resolve_collection_edits as _resolve_collection_edits,
)
from app.services.proposals.anchors import (
    _resolve_edit_ops as _resolve_edit_ops,
)
from app.services.proposals.anchors import (
    _resolve_text_edits as _resolve_text_edits,
)
from app.services.proposals.anchors import (
    _strip_entity_heading_echo as _strip_entity_heading_echo,
)
from app.services.proposals.anchors import (
    cv_synth_narration_refs as cv_synth_narration_refs,
)
from app.services.proposals.anchors import (
    read_key_for_op as read_key_for_op,
)
from app.services.proposals.anchors import (
    resolve_cv_set_bullets as resolve_cv_set_bullets,
)
from app.services.proposals.anchors import (
    resolve_cv_synth_payload as resolve_cv_synth_payload,
)
from app.services.proposals.anchors import (
    resolve_ops as resolve_ops,
)
from app.services.proposals.apply import ApplyMixin as ApplyMixin
from app.services.proposals.diff import (
    _LIST_FIELD_KEYS as _LIST_FIELD_KEYS,
)
from app.services.proposals.diff import (
    _LIST_FIELDS as _LIST_FIELDS,
)
from app.services.proposals.diff import (
    DiffMixin as DiffMixin,
)
from app.services.proposals.diff import (
    _before_value as _before_value,
)
from app.services.proposals.diff import (
    _cv_choice_diff as _cv_choice_diff,
)
from app.services.proposals.diff import (
    _cv_choice_label as _cv_choice_label,
)
from app.services.proposals.diff import (
    _edit_summary_rows as _edit_summary_rows,
)
from app.services.proposals.diff import (
    _instance_jsonish as _instance_jsonish,
)
from app.services.proposals.diff import (
    _jsonish as _jsonish,
)
from app.services.proposals.diff import (
    _payload_value as _payload_value,
)
from app.services.proposals.diff import (
    _scalar_list as _scalar_list,
)
from app.services.proposals.diff import (
    _structured_entries as _structured_entries,
)
from app.services.proposals.diff import (
    _truncate as _truncate,
)
from app.services.proposals.kinds import (
    _HEADING_ECHO_KINDS as _HEADING_ECHO_KINDS,
)
from app.services.proposals.kinds import (
    _REVERT_TOLERANCE as _REVERT_TOLERANCE,
)
from app.services.proposals.kinds import (
    _SECTION_MODELS as _SECTION_MODELS,
)
from app.services.proposals.kinds import (
    ACTION_VERBS as ACTION_VERBS,
)
from app.services.proposals.kinds import (
    DIFF_VALUE_CAP as DIFF_VALUE_CAP,
)
from app.services.proposals.kinds import (
    GROUNDED_KINDS as GROUNDED_KINDS,
)
from app.services.proposals.kinds import (
    KIND_SPECS as KIND_SPECS,
)
from app.services.proposals.kinds import (
    PROPOSAL_TTL as PROPOSAL_TTL,
)
from app.services.proposals.kinds import (
    SECTION_NAMES as SECTION_NAMES,
)
from app.services.proposals.kinds import (
    TEXT_FIELDS as TEXT_FIELDS,
)
from app.services.proposals.kinds import (
    KindSpec as KindSpec,
)
from app.services.proposals.kinds import (
    _validate_choice_options as _validate_choice_options,
)
from app.services.proposals.preview import PreviewMixin as PreviewMixin
from app.services.proposals.service import (
    ProfileProposalService as ProfileProposalService,
)
from app.services.proposals.snapshots import (
    _SNAPSHOT_SKIP as _SNAPSHOT_SKIP,
)
from app.services.proposals.snapshots import (
    _full_snapshot as _full_snapshot,
)
from app.services.proposals.snapshots import (
    _snapshot_children as _snapshot_children,
)
from app.services.proposals.telemetry import (
    drop_code as drop_code,
)
from app.services.proposals.telemetry import (
    notify_proposals as notify_proposals,
)
from app.services.proposals.telemetry import (
    proposal_event as proposal_event,
)
from app.services.proposals.telemetry import (
    proposal_title as proposal_title,
)
