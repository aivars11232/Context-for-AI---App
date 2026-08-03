"""Canonical non-model clarification questions for TASK-0007."""

from __future__ import annotations

from collections.abc import Iterable

from context_for_ai.domain.enums import ClarificationReason
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ClarificationRequest
from context_for_ai.domain.ports.context import ClarificationBuildRequest
from context_for_ai.domain.value_objects import FrozenJsonObject


def _text(details: FrozenJsonObject, key: str) -> str:
    try:
        value = details[key]
    except KeyError as error:
        raise LifecycleInvariantError(
            f"Clarification details require {key}."
        ) from error
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(
            f"Clarification detail {key} must be non-empty text."
        )
    return value


def _texts(details: FrozenJsonObject, key: str) -> tuple[str, ...]:
    try:
        value = details[key]
    except KeyError as error:
        raise LifecycleInvariantError(
            f"Clarification details require {key}."
        ) from error
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise LifecycleInvariantError(
            f"Clarification detail {key} must be a text collection."
        )
    values = tuple(value)
    if not values or any(not isinstance(item, str) or not item.strip() for item in values):
        raise LifecycleInvariantError(
            f"Clarification detail {key} must contain non-empty text."
        )
    return values


class DeterministicClarificationBuilder:
    """Build one canonical clarification request without side effects."""

    def build(self, request: ClarificationBuildRequest) -> ClarificationRequest:
        details = request.details
        reason = request.reason
        if reason is ClarificationReason.AMBIGUOUS_REFERENCE:
            entity_type = _text(details, "entity_type")
            surface = _text(details, "surface_text")
            candidates = _texts(details, "candidate_labels")
            question = (
                f'Which {entity_type} do you mean by "{surface}"? '
                f'{", ".join(candidates)}'
            )
        elif reason is ClarificationReason.UNRESOLVED_REFERENCE:
            surface = _text(details, "surface_text")
            question = f'Please clarify what "{surface}" refers to.'
        elif reason is ClarificationReason.LOW_CONFIDENCE_INTERPRETATION:
            candidates = _texts(details, "candidate_intents")
            question = f'Please clarify whether you want: {", ".join(candidates)}.'
        elif reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT:
            rule_a = _text(details, "rule_a")
            rule_b = _text(details, "rule_b")
            question = f'Which instruction should apply: "{rule_a}" or "{rule_b}"?'
        elif reason is ClarificationReason.UNSUPPORTED_INTENT:
            question = "Please clarify the text-only result you want."
        elif reason is ClarificationReason.UNSUPPORTED_CONDITION:
            question = (
                "Please restate the condition using the supported output-type "
                "or active-project form."
            )
        elif reason is ClarificationReason.MATERIAL_ASSUMPTION:
            assumed_rule = _text(details, "assumed_rule")
            question = f'Please confirm the assumption: "{assumed_rule}".'
        else:  # pragma: no cover - the enum is exhaustive
            raise LifecycleInvariantError(f"Unsupported clarification reason: {reason}.")

        output_details = {key: details[key] for key in details}
        output_details["reason"] = reason.value
        return ClarificationRequest(
            request.clarification_request_id,
            request.processing_run_id,
            reason,
            question,
            FrozenJsonObject(output_details),
            request.created_at,
        )


__all__ = ["DeterministicClarificationBuilder"]
