"""Pluggable question-kind registry (Phase 23; plan 37 registry v2).

Each kind validates a raw answer and turns it into structured derived
deltas. Skipped questions derive nothing — skips are neutral by design
(same fairness stance as plan 22), never zeroing.

Delta shape produced by every kind:
  {"skill_levels": {skill_key: level}, "interest_keys": [tag_key, ...]}
plus optional side-channels: {"constraints": {key: value}} for
eligibility gates (plan-22 semantics — never skill deltas) and
{"evidence": "..."} for prose answers.

Plan-37 registry v2: kinds are registered objects carrying
`scoring_capable` metadata; new kinds arrive via the
`career_assistant.question_kinds` entry-point group and must pass the
contract kit (schema round-trip + scoring parity) to register.
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import Protocol

from app.core.errors import ValidationError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.question_kinds"


class QuestionKindHandler(Protocol):
    """One kind = answer schema (validate) + scoring handler (derive)."""

    scoring_capable: bool

    def validate(self, question: dict, answer) -> dict:
        """Normalize + validate an answer payload; raises ValidationError."""
        ...

    def derive(self, question: dict, answer: dict) -> dict:
        """Compute structured deltas for the validated answer."""
        ...


def _find_option(question: dict, option_id: str) -> dict:
    for option in question.get("options") or []:
        if option.get("id") == option_id:
            return option
    raise ValidationError("Answer does not match this question's options")


def _merge(merged: dict, option: dict, share: float = 1.0) -> None:
    scores = option.get("scores") or {}
    for key, value in (scores.get("skill_levels") or {}).items():
        merged["skill_levels"][key] = (
            merged["skill_levels"].get(key, 0) + float(value) * share
        )
    for key in scores.get("interest_keys") or []:
        if key not in merged["interest_keys"]:
            merged["interest_keys"].append(key)


class ScenarioMcq:
    """Single-choice scenario; the chosen option carries the deltas."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "option_id" not in answer:
            raise ValidationError("scenario_mcq answer needs {option_id}")
        _find_option(question, str(answer["option_id"]))
        return {"option_id": str(answer["option_id"])}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        _merge(merged, _find_option(question, answer["option_id"]))
        return merged


class TimeAllocation:
    """Percentages across options summing to 100 — weighted deltas."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or not isinstance(answer.get("weights"), dict):
            raise ValidationError("time_allocation answer needs {weights{}}")
        weights = {str(k): int(v) for k, v in answer["weights"].items()}
        ids = {o["id"] for o in question.get("options") or []}
        if not set(weights) <= ids:
            raise ValidationError("weights reference unknown options")
        if any(v < 0 or v > 100 for v in weights.values()):
            raise ValidationError("weights must be 0–100")
        if sum(weights.values()) not in (0, 100):
            raise ValidationError("allocation must sum to 100 (or 0 to skip)")
        return {"weights": weights}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        for option in question.get("options") or []:
            share = answer["weights"].get(option["id"], 0) / 100.0
            if share <= 0:
                continue
            _merge(merged, option, share)
        return merged


class Ranking:
    """Ordered option ids; earlier positions carry more weight."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or not isinstance(answer.get("order"), list):
            raise ValidationError("ranking answer needs {order: [option_ids]}")
        ids = {o["id"] for o in question.get("options") or []}
        order = [str(o) for o in answer["order"]]
        if len(order) != len(ids) or set(order) != ids:
            raise ValidationError("ranking must include every option exactly once")
        return {"order": order}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        n = max(1, len(answer["order"]))
        for rank, option_id in enumerate(answer["order"]):
            _merge(merged, _find_option(question, option_id), (n - rank) / n)
        return merged


class Slider:
    """A 1–10 self-rating; time_split carries what is being rated."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "value" not in answer:
            raise ValidationError("slider answer needs {value}")
        value = int(answer["value"])
        if not 1 <= value <= 10:
            raise ValidationError("slider value must be 1–10")
        return {"value": value}

    def derive(self, question: dict, answer: dict) -> dict:
        skill_key = (question.get("time_split") or {}).get("skill_key")
        if not skill_key:
            return {"skill_levels": {}, "interest_keys": []}
        return {
            "skill_levels": {skill_key: float(answer["value"])},
            "interest_keys": [],
        }


class MultiSelect:
    """Choose k-of-n (chips); per-option deltas, k bounds enforced."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or not isinstance(answer.get("selected"), list):
            raise ValidationError("multi_select answer needs {selected: [ids]}")
        ids = {o["id"] for o in question.get("options") or []}
        selected = [str(o) for o in answer["selected"]]
        if not set(selected) <= ids:
            raise ValidationError("selected references unknown options")
        if len(set(selected)) != len(selected):
            raise ValidationError("duplicate selections")
        config = question.get("time_split") or {}
        min_k = int(config.get("min_select", 0))
        max_k = int(config.get("max_select", len(ids)))
        if not min_k <= len(selected) <= max_k:
            raise ValidationError(f"select between {min_k} and {max_k} options")
        return {"selected": selected}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        for option_id in answer["selected"]:
            _merge(merged, _find_option(question, option_id))
        return merged


class ForcedChoice:
    """Pick between 2–4 statement blocks — the modern personality format
    (less social-desirability bias than Likert-only)."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "option_id" not in answer:
            raise ValidationError("forced_choice answer needs {option_id}")
        options = question.get("options") or []
        if not 2 <= len(options) <= 4:
            raise ValidationError("forced_choice needs 2–4 blocks")
        _find_option(question, str(answer["option_id"]))
        return {"option_id": str(answer["option_id"])}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        _merge(merged, _find_option(question, answer["option_id"]))
        return merged


class LikertMatrix:
    """Statements × agreement scale (1–5) with reverse-score flags.

    Per statement: `(agreement − 3) / 2` scales the statement's delta
    (−1…+1), sign-flipped for reverse-scored statements. Neutral (3)
    contributes nothing — skips stay neutral.
    """

    scoring_capable = True

    def _statements(self, question: dict) -> dict[str, dict]:
        return {
            str(s["id"]): s
            for s in (question.get("time_split") or {}).get("statements") or []
        }

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or not isinstance(answer.get("values"), dict):
            raise ValidationError("likert_matrix answer needs {values{}}")
        statements = self._statements(question)
        if not statements:
            raise ValidationError("question has no statements")
        values = {}
        for statement_id, value in answer["values"].items():
            if str(statement_id) not in statements:
                raise ValidationError("values reference unknown statements")
            v = int(value)
            if not 1 <= v <= 5:
                raise ValidationError("agreement values must be 1–5")
            values[str(statement_id)] = v
        return {"values": values}

    def derive(self, question: dict, answer: dict) -> dict:
        merged = {"skill_levels": {}, "interest_keys": []}
        statements = self._statements(question)
        for statement_id, value in answer["values"].items():
            statement = statements[statement_id]
            weight = (value - 3) / 2.0
            if statement.get("reverse"):
                weight = -weight
            if abs(weight) < 1e-9:
                continue
            scores = statement.get("scores") or {}
            for key, delta in (scores.get("skill_levels") or {}).items():
                merged["skill_levels"][key] = (
                    merged["skill_levels"].get(key, 0) + float(delta) * weight
                )
            for key in scores.get("interest_keys") or []:
                if key not in merged["interest_keys"]:
                    merged["interest_keys"].append(key)
        return merged


class NumericInput:
    """Bounded number (hours, years) — scaled skill delta or constraint."""

    scoring_capable = True

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "value" not in answer:
            raise ValidationError("numeric_input answer needs {value}")
        config = question.get("time_split") or {}
        try:
            value = float(answer["value"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("value must be numeric") from exc
        minimum = config.get("min")
        maximum = config.get("max")
        if minimum is not None and value < float(minimum):
            raise ValidationError(f"value must be ≥ {minimum}")
        if maximum is not None and value > float(maximum):
            raise ValidationError(f"value must be ≤ {maximum}")
        return {"value": value}

    def derive(self, question: dict, answer: dict) -> dict:
        config = question.get("time_split") or {}
        skill_key = config.get("skill_key")
        if not skill_key:
            return {"skill_levels": {}, "interest_keys": []}
        per_unit = float(config.get("per_unit", 1.0))
        cap = float(config.get("cap", 10.0))
        delta = min(cap, max(0.0, float(answer["value"])) * per_unit)
        return {
            "skill_levels": {skill_key: delta},
            "interest_keys": [],
        }


class EligibilityGate:
    """Factual boolean/select (license, work auth) — feeds plan-22 gates,
    never skill deltas."""

    scoring_capable = False

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "option_id" not in answer:
            raise ValidationError("eligibility_gate answer needs {option_id}")
        _find_option(question, str(answer["option_id"]))
        return {"option_id": str(answer["option_id"])}

    def derive(self, question: dict, answer: dict) -> dict:
        option = _find_option(question, answer["option_id"])
        constraint_key = (question.get("time_split") or {}).get("constraint_key")
        if not constraint_key:
            return {"skill_levels": {}, "interest_keys": []}
        value = (option.get("scores") or {}).get("constraint_value")
        return {
            "skill_levels": {},
            "interest_keys": [],
            "constraints": {constraint_key: value},
        }


class ShortText:
    """Free prose — evidence-only: stored, AI-summarizable, no deltas."""

    scoring_capable = False

    def validate(self, question: dict, answer) -> dict:
        if not isinstance(answer, dict) or "text" not in answer:
            raise ValidationError("short_text answer needs {text}")
        text = str(answer["text"]).strip()
        if len(text) > 2000:
            raise ValidationError("text must be ≤ 2000 characters")
        return {"text": text}

    def derive(self, question: dict, answer: dict) -> dict:
        return {
            "skill_levels": {},
            "interest_keys": [],
            "evidence": answer["text"],
        }


BUILTIN_KINDS: dict[str, type] = {
    "scenario_mcq": ScenarioMcq,
    "single_select": ScenarioMcq,
    "time_allocation": TimeAllocation,
    "ranking": Ranking,
    "slider": Slider,
    "multi_select": MultiSelect,
    "forced_choice": ForcedChoice,
    "likert_matrix": LikertMatrix,
    "numeric_input": NumericInput,
    "eligibility_gate": EligibilityGate,
    "short_text": ShortText,
}

REGISTRY: dict[str, type] = dict(BUILTIN_KINDS)
_plugins_loaded = False


def _load_kind_plugins() -> None:
    """Entry-point kinds must pass the contract kit to register."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            handler_cls = ep.load()
            probe = handler_cls()
            _contract_check(ep.name, probe)
        except Exception as exc:  # noqa: BLE001 — one bad kind never breaks boot
            logger.warning("Question kind %s failed the contract kit: %s", ep.name, exc)
            continue
        REGISTRY.setdefault(ep.name, handler_cls)


def _contract_check(name: str, handler: QuestionKindHandler) -> None:
    """Minimal kit: a question round-trips a valid answer and, when the
    kind is scoring-capable, actually produces deltas."""
    if not hasattr(handler, "validate") or not hasattr(handler, "derive"):
        raise ValidationError(f"kind {name} lacks validate/derive")
    if not isinstance(getattr(handler, "scoring_capable", None), bool):
        raise ValidationError(f"kind {name} lacks scoring_capable metadata")


def reset_registry() -> None:
    """Test hook: drop plugin kinds (built-ins stay)."""
    global _plugins_loaded
    for key in list(REGISTRY):
        if key not in BUILTIN_KINDS:
            del REGISTRY[key]
    _plugins_loaded = False


def handler_for(kind: str) -> QuestionKindHandler:
    _load_kind_plugins()
    handler = REGISTRY.get(kind)
    if handler is None:
        raise ValidationError(f"Unsupported question kind: {kind}")
    return handler()


def is_scoring_capable(kind: str) -> bool:
    _load_kind_plugins()
    handler_cls = REGISTRY.get(kind)
    return bool(handler_cls and handler_cls().scoring_capable)
