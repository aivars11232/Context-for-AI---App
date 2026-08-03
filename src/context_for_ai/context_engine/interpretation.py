"""Deterministic rule-table interpretation for TASK-0007."""

from __future__ import annotations

from dataclasses import dataclass
import re

from context_for_ai.context_engine.normalization import (
    NormalizedText,
    PhraseMatch,
    find_phrase_matches,
    normalize_capture,
    normalize_text,
    split_action_object,
)
from context_for_ai.domain.decisions import (
    IntentCandidate,
    InterpretationDecision,
    MatchedRuleEvidence,
    QualifierMatch,
    ReferenceMention,
    RequestInterpretation,
)
from context_for_ai.domain.enums import (
    ClarificationReason,
    IntentType,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.configuration import ContextSettings
from context_for_ai.domain.ports.context import InterpretationRequest
from context_for_ai.domain.value_objects import FrozenJsonObject, UnitScore


_DEFAULT_OUTPUTS = {
    IntentType.ANSWER: OutputType.TEXT_ANSWER,
    IntentType.EXPLAIN: OutputType.TEXT_EXPLANATION,
    IntentType.DESCRIBE: OutputType.TEXT_DESCRIPTION,
    IntentType.PLAN: OutputType.TEXT_PLAN,
    IntentType.ANALYZE: OutputType.TEXT_ANALYSIS,
    IntentType.RESEARCH: OutputType.TEXT_ANALYSIS,
    IntentType.DEBUG: OutputType.TEXT_ANALYSIS,
    IntentType.EDIT_TEXT: OutputType.TEXT_ANSWER,
}
_CONTROL_INTENTS = frozenset({IntentType.CONTINUE, IntentType.CORRECT})
_CLAUSE_BOUNDARIES = ".,;!?"


@dataclass(frozen=True, slots=True)
class _QualifierCandidate:
    kind: QualifierKind
    rule_id: str
    match: PhraseMatch


@dataclass(frozen=True, slots=True)
class _UnsupportedMatch:
    category: str
    evidence: MatchedRuleEvidence


def _output_for_rule(rule: object, state_output: OutputType | None) -> OutputType:
    intent = IntentType(getattr(rule, "intent"))
    configured = getattr(rule, "output_type")
    if intent in _CONTROL_INTENTS:
        return state_output or OutputType.TEXT_ANSWER
    if configured is not None:
        return OutputType(configured)
    return _DEFAULT_OUTPUTS[intent]


def _evidence(rule_id: str, match: PhraseMatch, priority: int) -> MatchedRuleEvidence:
    return MatchedRuleEvidence(
        rule_id,
        match.matched_text,
        match.normalized_phrase,
        match.start_offset,
        match.end_offset,
        priority,
    )


def _clause_bounds(text: str, position: int) -> tuple[int, int]:
    left = 0
    right = len(text)
    for marker in _CLAUSE_BOUNDARIES:
        found = text.rfind(marker, 0, position)
        if found >= 0:
            left = max(left, found + 1)
        found = text.find(marker, position)
        if found >= 0:
            right = min(right, found)
    conjunction = " and "
    found = text.rfind(conjunction, 0, position)
    if found >= 0:
        left = max(left, found + len(conjunction))
    found = text.find(conjunction, position)
    if found >= 0:
        right = min(right, found)
    return left, right


def _capture_qualifier(
    normalized: NormalizedText,
    candidate: _QualifierCandidate,
) -> tuple[FrozenJsonObject, bool]:
    match = candidate.match
    kind = candidate.kind
    left, right = _clause_bounds(normalized.text, match.normalized_start)
    before = normalize_capture(normalized.text[left : match.normalized_start])
    after = normalize_capture(normalized.text[match.normalized_end : right])
    try:
        if kind is QualifierKind.ONLY:
            target = normalize_capture(f"{before} {after}")
            action, object_text = split_action_object(target)
            return FrozenJsonObject(
                {"target": target, "action": action, "object": object_text}
            ), False
        if kind is QualifierKind.EXACTLY:
            target = normalize_capture(f"{before.rsplit(' ', 1)[-1]} {after}")
            action, object_text = split_action_object(target)
            return FrozenJsonObject(
                {"target": target, "action": action, "object": object_text}
            ), False
        if kind is QualifierKind.APPROXIMATE:
            target = after
            if match.normalized_phrase == "roughly":
                target = normalize_capture(f"{before.rsplit(' ', 1)[-1]} {after}")
            action, object_text = split_action_object(target)
            return FrozenJsonObject(
                {"target": target, "action": action, "object": object_text}
            ), False
        if kind is QualifierKind.PROHIBITION:
            action, object_text = split_action_object(after)
            return FrozenJsonObject(
                {"target": after, "action": action, "object": object_text}
            ), False
        if kind is QualifierKind.PRESERVATION:
            if not after:
                raise ValueError("missing preserved object")
            return FrozenJsonObject({"object": after}), False
        if kind is QualifierKind.SUBSTITUTION:
            action, replacement = split_action_object(before)
            replaced_capture = after
            if not replaced_capture:
                raise ValueError("missing replaced alternative")
            if replaced_capture.startswith(f"{action} "):
                _, replaced_capture = split_action_object(replaced_capture)
            return FrozenJsonObject(
                {
                    "action": action,
                    "replacement": replacement,
                    "replaced": replaced_capture,
                }
            ), False
        if kind is QualifierKind.PRIOR_REFERENCE:
            return FrozenJsonObject({"reference": match.normalized_phrase}), False
        if kind is QualifierKind.SEQUENTIAL:
            return FrozenJsonObject(
                {"structure": "one ordered step at a time"}
            ), False
    except (ValueError, RuntimeError, LifecycleInvariantError):
        pass
    return FrozenJsonObject({"capture_error": "missing required qualifier operand"}), True


def _state_proposals(normalized_text: str) -> tuple[str | None, str | None]:
    topic_match = re.fullmatch(r"(?:topic:\s*|switch topic to\s+)(.+)", normalized_text)
    task_match = re.fullmatch(r"(?:task:\s*|new task:\s+)(.+)", normalized_text)
    topic = None if topic_match is None else topic_match.group(1).strip()
    task = None if task_match is None else task_match.group(1).strip()
    return topic or None, task or None


class DeterministicInterpretationEngine:
    """Interpret one message using only a validated versioned rule table."""

    def __init__(self, settings: ContextSettings) -> None:
        self._settings = settings

    def interpret(self, request: InterpretationRequest) -> InterpretationDecision:
        normalized = normalize_text(request.message.original_text)
        candidates: list[IntentCandidate] = []
        for rule in self._settings.intent_rules:
            for phrase in rule.phrases:
                for match in find_phrase_matches(normalized, phrase):
                    candidates.append(
                        IntentCandidate(
                            IntentType(rule.intent),
                            _output_for_rule(rule, request.state.expected_output_type),
                            _evidence(rule.id, match, rule.priority),
                        )
                    )
        candidates.sort(
            key=lambda item: (
                -item.evidence.priority,
                -len(item.evidence.normalized_phrase),
                item.evidence.rule_id,
                item.evidence.start_offset,
            )
        )

        selected: IntentCandidate | None = None
        tied_intents: tuple[IntentType, ...] = ()
        if candidates:
            top_priority = candidates[0].evidence.priority
            top_length = len(candidates[0].evidence.normalized_phrase)
            top = tuple(
                item
                for item in candidates
                if item.evidence.priority == top_priority
                and len(item.evidence.normalized_phrase) == top_length
            )
            tied_intents = tuple(dict.fromkeys(item.intent for item in top))
            if len(tied_intents) == 1:
                selected = min(
                    top,
                    key=lambda item: (
                        item.evidence.rule_id,
                        item.evidence.start_offset,
                    ),
                )

        unsupported_matches: list[_UnsupportedMatch] = []
        for rule in self._settings.unsupported_request_rules:
            for phrase in rule.phrases:
                for match in find_phrase_matches(normalized, phrase):
                    unsupported_matches.append(
                        _UnsupportedMatch(
                            rule.category,
                            _evidence(rule.id, match, 100),
                        )
                    )
        unsupported_matches.sort(
            key=lambda item: (
                item.evidence.start_offset,
                item.evidence.rule_id,
            )
        )

        qualifier_candidates: list[_QualifierCandidate] = []
        for rule in self._settings.qualifier_rules:
            for phrase in rule.phrases:
                for match in find_phrase_matches(normalized, phrase):
                    qualifier_candidates.append(
                        _QualifierCandidate(
                            QualifierKind(rule.qualifier),
                            rule.id,
                            match,
                        )
                    )
        qualifier_candidates.sort(
            key=lambda item: (
                item.match.start_offset,
                -len(item.match.normalized_phrase),
                item.rule_id,
            )
        )
        selected_qualifiers: list[_QualifierCandidate] = []
        for item in qualifier_candidates:
            if any(
                item.match.start_offset < existing.match.end_offset
                and existing.match.start_offset < item.match.end_offset
                for existing in selected_qualifiers
            ):
                continue
            selected_qualifiers.append(item)

        qualifier_matches: list[QualifierMatch] = []
        references: list[ReferenceMention] = []
        capture_failure = False
        for item in selected_qualifiers:
            captures, failed = _capture_qualifier(normalized, item)
            capture_failure = capture_failure or failed
            match = item.match
            qualifier_matches.append(
                QualifierMatch(
                    item.kind,
                    item.rule_id,
                    match.matched_text,
                    match.normalized_phrase,
                    match.start_offset,
                    match.end_offset,
                    captures,
                )
            )
            if item.kind is QualifierKind.PRIOR_REFERENCE:
                references.append(
                    ReferenceMention(
                        len(references),
                        match.matched_text,
                        match.normalized_phrase,
                        item.rule_id,
                        match.start_offset,
                        match.end_offset,
                    )
                )

        clarification_reason: ClarificationReason | None = None
        details: FrozenJsonObject | None = None
        result_intent = IntentType.UNSUPPORTED
        output_type = OutputType.CLARIFICATION
        intent_rule_id: str | None = None
        confidence = UnitScore("0")
        reason = "no deterministic intent rule matched"

        if len(tied_intents) > 1:
            clarification_reason = ClarificationReason.LOW_CONFIDENCE_INTERPRETATION
            details = FrozenJsonObject(
                {
                    "candidate_intents": [intent.value for intent in tied_intents],
                    "rule_ids": [item.evidence.rule_id for item in candidates],
                }
            )
            reason = "different intents tied at canonical rank"
        elif selected is None:
            clarification_reason = ClarificationReason.UNSUPPORTED_INTENT
            details = FrozenJsonObject(
                {
                    "candidate_intents": [],
                    "unsupported_rule_ids": [
                        item.evidence.rule_id for item in unsupported_matches
                    ],
                    "unsupported_categories": [
                        item.category for item in unsupported_matches
                    ],
                }
            )
            if unsupported_matches:
                reason = "unsupported image or external-action request"
        else:
            explicit_description = (
                selected.intent is IntentType.DESCRIBE
                and selected.output_type is OutputType.TEXT_DESCRIPTION
            )
            explicit_text_prompt = (
                selected.intent is IntentType.EDIT_TEXT
                and selected.output_type is OutputType.TEXT_ANSWER
                and "text prompt" in selected.evidence.normalized_phrase
            )
            if unsupported_matches and not (
                explicit_description or explicit_text_prompt
            ):
                clarification_reason = ClarificationReason.UNSUPPORTED_INTENT
                details = FrozenJsonObject(
                    {
                        "unsupported_rule_ids": [
                            item.evidence.rule_id for item in unsupported_matches
                        ],
                        "unsupported_categories": [
                            item.category for item in unsupported_matches
                        ],
                    }
                )
                intent_rule_id = selected.evidence.rule_id
                reason = "unsupported image or external-action request"
            elif capture_failure:
                result_intent = selected.intent
                output_type = OutputType.CLARIFICATION
                intent_rule_id = selected.evidence.rule_id
                confidence = UnitScore("0.49")
                clarification_reason = (
                    ClarificationReason.LOW_CONFIDENCE_INTERPRETATION
                )
                details = FrozenJsonObject(
                    {
                        "candidate_intents": [selected.intent.value],
                        "qualifier_rule_ids": [
                            item.rule_id
                            for item in selected_qualifiers
                            if "capture_error"
                            in qualifier_matches[
                                selected_qualifiers.index(item)
                            ].captures
                        ],
                    }
                )
                reason = "a matched qualifier has an incomplete capture"
            else:
                result_intent = selected.intent
                output_type = selected.output_type
                intent_rule_id = selected.evidence.rule_id
                confidence = UnitScore("1")
                reason = f"selected deterministic rule {intent_rule_id}"

        topic, task = _state_proposals(normalized.text)
        interpretation = RequestInterpretation(
            request.processing_run_id,
            request.message.id,
            result_intent,
            output_type,
            intent_rule_id,
            tuple(qualifier_matches),
            confidence,
            reason,
            request.evaluated_at,
        )
        return InterpretationDecision(
            interpretation,
            self._settings.rule_set_version,
            tuple(candidates),
            topic,
            task,
            tuple(references),
            clarification_reason,
            details,
        )


__all__ = ["DeterministicInterpretationEngine"]
