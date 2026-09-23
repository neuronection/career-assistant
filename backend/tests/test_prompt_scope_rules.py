"""Plan-109 prompt-lock tests: scope honesty in the chat + builder prompts.

The assistant's CV-entry routing broke in the field because the
instructions never said bullets and descriptions render independently.
These assertions pin the v13 prompt lines so a later prompt rewrite
cannot silently drop the rules; strings are checked against the
whitespace-normalized prompt text (single-line quotes must span)
because the sources are hard-wrapped literals.
"""

from app.ai.agents.cv_builder_chat import SYSTEM
from app.ai.agents.prompts import AGENT_ROUND, CHATBOT


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_planner_inspects_both_fields_and_states_layers():
    prompt = _flat(CHATBOT)
    assert "INDEPENDENT layers and BOTH print" in prompt
    assert "Inspect both fields before proposing anything" in prompt
    assert "a bullet-only rewrite does NOT shorten the entry" in prompt


def test_planner_scope_narration_and_honesty_guard():
    prompt = _flat(CHATBOT)
    assert "SCOPE NARRATION" in prompt
    assert "reversible via unpin" in prompt
    assert (
        "Never present a bullet-only rewrite as making the entry concise/shorter"
        in prompt
    )
    assert "name what stays unchanged" in prompt


def test_planner_routing_prefers_variants_for_whole_entry():
    prompt = _flat(CHATBOT)
    assert "PREFER a CV-scoped synthesized variant" in prompt
    assert "A bullet-only path" in prompt


def test_variant_list_verdict_discipline():
    prompt = _flat(CHATBOT)
    assert "ALWAYS call it with the attached CV's id VERBATIM" in prompt
    assert (
        "ONLY rows with a pin/applicable verdict may be claimed as rendering" in prompt
    )
    agent = _flat(AGENT_ROUND)
    assert "applicability verdicts" in agent
    assert "never claim a variant renders on the CV" in agent


def test_builder_prompt_carries_the_scope_rules():
    prompt = _flat(SYSTEM)
    assert "SCOPE FIRST" in prompt
    assert "independent layers and BOTH print" in prompt
    # The prefer-clause names a REAL op: the copilot vocabulary carries
    # `upsert_variant` (full-entry restyle) — an invented op literal is
    # exactly what killed structured turns before (send_failed ST-1).
    assert "PREFER the upsert_variant op" in prompt
    assert "upsert_variant {" in prompt
    assert "State the scope in one line" in prompt
    assert "never pitch a bullets-only rewrite as making the entry concise" in prompt


def test_choice_card_routing_rules_locked():
    prompt = _flat(CHATBOT)
    assert "MULTI-SELECT CHOICE CARD" in prompt
    assert "do NOT pick unilaterally and do NOT ask a text question" in prompt
    assert "NEVER kind cv_choice itself" in prompt
    assert "each chosen option becomes a normal approval card" in prompt
