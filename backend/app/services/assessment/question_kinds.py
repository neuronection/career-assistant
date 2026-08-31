"""Pluggable question-kind registry (Phase 23; plan 37 grows it).

Each kind validates a raw answer and turns it into structured derived
deltas. Skipped questions derive nothing — skips are neutral by design
(same fairness stance as plan 22), never zeroing.

Delta shape produced by every kind:
  {"skill_levels": {skill_key: level}, "interest_keys": [tag_key, ...]}
"""

from __future__ import annotations

from typing import Protocol

from app.core.errors import ValidationError


class QuestionKindHandler(Protocol):
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


REGISTRY: dict[str, type] = {
    "scenario_mcq": ScenarioMcq,
    "time_allocation": TimeAllocation,
    "ranking": Ranking,
    "slider": Slider,
}


def handler_for(kind: str) -> QuestionKindHandler:
    handler = REGISTRY.get(kind)
    if handler is None:
        raise ValidationError(f"Unsupported question kind: {kind}")
    return handler()
