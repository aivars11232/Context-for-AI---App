"""Pure deterministic validation of one fully buffered model response."""

from __future__ import annotations

from dataclasses import dataclass
import re

from context_for_ai.context_engine.normalization import (
    NormalizedWordToken,
    SentenceSpan,
    find_casefolded_literal_spans,
    normalize_word_tokens,
    normalize_words,
    split_sentence_spans,
)
from context_for_ai.domain.decisions import (
    CONDITION_GRAMMAR_VERSION,
    CONTEXT_PACKET_SCHEMA_VERSION,
)
from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
    ConstraintResolutionStatus,
    ConstraintType,
    OutputType,
    ValidationCheckId,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
    ValidationViolationCode,
    ValidationWarningCode,
)
from context_for_ai.domain.errors import (
    DomainValidationError,
    LifecycleInvariantError,
)
from context_for_ai.domain.lifecycle import (
    MatchLocation,
    ValidationEvidence,
    ValidationResult,
    ValidationViolation,
    ValidationViolationEvidence,
    calculate_validation_score,
    validation_violation_message,
)
from context_for_ai.domain.ports.context import ValidationRequest
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


_ATOM = r"[A-Z0-9]+(?:_[A-Z0-9]+)*"
_REQUIRED_PREDICATE = re.compile(rf"MUST_({_ATOM}):({_ATOM})\Z")
_FORBIDDEN_PREDICATE = re.compile(rf"MUST_NOT_({_ATOM}):({_ATOM})\Z")
_PRESERVE_PREDICATE = re.compile(rf"MUST_PRESERVE:({_ATOM})\Z")
_PREFERRED_PREDICATE = re.compile(rf"PREFER_({_ATOM}):({_ATOM})\Z")
_OPTIONAL_PREDICATE = re.compile(rf"MAY_({_ATOM}):({_ATOM})\Z")
_ASSUMED_PREDICATE = re.compile(rf"ASSUME_({_ATOM}):({_ATOM})\Z")
_NUMBERED_ITEM = re.compile(r"([1-9][0-9]*)\.\s+\S.*\Z")
_OPENING_FENCE = re.compile(r"```(?:[^\s`]+)?\Z")
_COMPARISON_ITEM = re.compile(r"[-*] (.+)\Z")
_MODEL_OUTPUT_TYPES = frozenset(
    output_type
    for output_type in OutputType
    if output_type not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
)
_HARD_CONSTRAINT_TYPES = frozenset(
    {ConstraintType.REQUIRED, ConstraintType.FORBIDDEN, ConstraintType.PRESERVE}
)
_EXPLANATION = {
    ValidationOutcome.PASSED: "The deterministic predicate passed.",
    ValidationOutcome.FAILED: "The deterministic predicate failed.",
    ValidationOutcome.WARNING:
        "A non-failing deterministic warning was recorded.",
    ValidationOutcome.NOT_APPLICABLE:
        "The check is not applicable to this packet.",
}
_VIOLATION_BY_CHECK = {
    ValidationCheckId.TOPIC: ValidationViolationCode.TOPIC_MISMATCH,
    ValidationCheckId.OUTPUT_SHAPE: ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
    ValidationCheckId.ACTION_MARKER: ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
    ValidationCheckId.REQUIRED_CONSTRAINT:
        ValidationViolationCode.MISSING_REQUIREMENT,
    ValidationCheckId.FORBIDDEN_CONSTRAINT:
        ValidationViolationCode.FORBIDDEN_ACTION,
    ValidationCheckId.PRESERVE_CONSTRAINT:
        ValidationViolationCode.PRESERVATION_VIOLATION,
    ValidationCheckId.CONDITIONAL_CONSTRAINT:
        ValidationViolationCode.CONDITIONAL_VIOLATION,
}


def _invariant(message: str, error: Exception | None = None) -> LifecycleInvariantError:
    result = LifecycleInvariantError(message)
    if error is not None:
        result.__cause__ = error
    return result


def _object(value: object, field_name: str) -> FrozenJsonObject:
    if not isinstance(value, FrozenJsonObject):
        raise LifecycleInvariantError(f"{field_name} must be an immutable JSON object.")
    return value


def _array(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise LifecycleInvariantError(f"{field_name} must be an immutable JSON array.")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")
    return value


def _uint(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be a non-negative integer.")
    return value


def _enum_value(enum_type: type, value: object, field_name: str) -> object:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise _invariant(f"{field_name} must be canonical.", error)


def _atom_tokens(atom: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in atom.split("_"))


@dataclass(frozen=True, slots=True)
class _ParsedPredicate:
    form: str
    action_tokens: tuple[str, ...]
    object_tokens: tuple[str, ...]


def _parse_predicate(
    constraint_type: ConstraintType,
    predicate: str,
) -> _ParsedPredicate:
    """Parse exactly one production from the canonical constraint grammar."""

    if constraint_type is ConstraintType.REQUIRED:
        match = _REQUIRED_PREDICATE.fullmatch(predicate)
        if match is None:
            raise LifecycleInvariantError(
                "A REQUIRED constraint has a malformed canonical predicate."
            )
        action, object_value = match.groups()
        if action.startswith("NOT_") or action == "PRESERVE":
            raise LifecycleInvariantError(
                "A REQUIRED predicate uses another constraint type's production."
            )
        if action == "EXACTLY":
            return _ParsedPredicate("exact", (), _atom_tokens(object_value))
        if (
            action == "PRESENT"
            and object_value == "ONE_ORDERED_STEP_AT_A_TIME"
        ):
            return _ParsedPredicate("ordered_step", (), ())
        return _ParsedPredicate(
            "action_object",
            _atom_tokens(action),
            _atom_tokens(object_value),
        )

    patterns = {
        ConstraintType.FORBIDDEN: _FORBIDDEN_PREDICATE,
        ConstraintType.PRESERVE: _PRESERVE_PREDICATE,
        ConstraintType.PREFERRED: _PREFERRED_PREDICATE,
        ConstraintType.OPTIONAL: _OPTIONAL_PREDICATE,
        ConstraintType.ASSUMED: _ASSUMED_PREDICATE,
    }
    pattern = patterns.get(constraint_type)
    if pattern is None:
        raise LifecycleInvariantError(
            "A conditional predicate requires a legal hard underlying type."
        )
    match = pattern.fullmatch(predicate)
    if match is None:
        raise LifecycleInvariantError(
            f"A {constraint_type.value} constraint has a malformed canonical predicate."
        )
    groups = match.groups()
    if constraint_type is ConstraintType.PRESERVE:
        return _ParsedPredicate("preserve", (), _atom_tokens(groups[0]))
    return _ParsedPredicate(
        "action_object",
        _atom_tokens(groups[0]),
        _atom_tokens(groups[1]),
    )


@dataclass(frozen=True, slots=True)
class _ConstraintPolicy:
    id: DomainId
    constraint_type: ConstraintType
    underlying_type: ConstraintType | None
    status: ConstraintResolutionStatus
    predicate: str
    parsed_predicate: _ParsedPredicate
    condition_evaluation: ConditionEvaluation | None


@dataclass(frozen=True, slots=True)
class _PacketPolicy:
    topic_terms: tuple[str, ...]
    output_type: OutputType
    output_shape: str
    output_shape_rule_id: str
    preserve_verb_list_id: str
    preserve_verbs: tuple[str, ...]
    action_markers: tuple[str, ...]
    constraints: tuple[_ConstraintPolicy, ...]


def _condition_evaluation(
    raw_condition: object,
    status: ConstraintResolutionStatus,
) -> ConditionEvaluation:
    condition = _object(raw_condition, "packet constraint condition")
    if set(condition) != {
        "grammar_version",
        "kind",
        "expected_value",
        "evaluation",
    }:
        raise LifecycleInvariantError(
            "A conditional constraint requires the exact condition fields."
        )
    if condition["grammar_version"] != CONDITION_GRAMMAR_VERSION:
        raise LifecycleInvariantError("Packet condition grammar is unsupported.")
    _enum_value(ConditionKind, condition["kind"], "packet condition kind")
    _text(condition["expected_value"], "packet condition expected value")
    evaluation = _enum_value(
        ConditionEvaluation,
        condition["evaluation"],
        "packet condition evaluation",
    )
    assert isinstance(evaluation, ConditionEvaluation)
    if evaluation is ConditionEvaluation.UNSUPPORTED:
        raise LifecycleInvariantError(
            "An unsupported condition cannot reach response validation."
        )
    if evaluation is ConditionEvaluation.FALSE:
        if status is not ConstraintResolutionStatus.INACTIVE:
            raise LifecycleInvariantError(
                "A false conditional constraint must be inactive."
            )
    elif status is ConstraintResolutionStatus.INACTIVE:
        raise LifecycleInvariantError(
            "An inactive conditional constraint must have a false condition."
        )
    return evaluation


def _constraint_policy(raw_value: object) -> _ConstraintPolicy:
    raw = _object(raw_value, "packet constraint")
    constraint_type = _enum_value(
        ConstraintType,
        raw["type"],
        "packet constraint type",
    )
    status = _enum_value(
        ConstraintResolutionStatus,
        raw["status"],
        "packet constraint status",
    )
    assert isinstance(constraint_type, ConstraintType)
    assert isinstance(status, ConstraintResolutionStatus)
    if status is ConstraintResolutionStatus.CONFLICTING:
        raise LifecycleInvariantError(
            "A successful context packet cannot contain conflicting constraints."
        )

    try:
        constraint_id = DomainId(raw["id"])  # type: ignore[arg-type]
    except (DomainValidationError, TypeError, ValueError) as error:
        raise _invariant("Packet constraint ID must be canonical.", error)
    predicate = _text(raw["normalized_rule"], "packet constraint predicate")
    underlying_raw = raw["underlying_type"]
    condition_raw = raw["condition"]

    if constraint_type is ConstraintType.CONDITIONAL:
        underlying_type = _enum_value(
            ConstraintType,
            underlying_raw,
            "packet conditional underlying type",
        )
        assert isinstance(underlying_type, ConstraintType)
        if underlying_type not in _HARD_CONSTRAINT_TYPES:
            raise LifecycleInvariantError(
                "A conditional constraint requires a hard underlying type."
            )
        condition_evaluation = _condition_evaluation(condition_raw, status)
        parsed = _parse_predicate(underlying_type, predicate)
    else:
        if underlying_raw is not None or condition_raw is not None:
            raise LifecycleInvariantError(
                "Only conditional constraints may carry conditional fields."
            )
        if status is ConstraintResolutionStatus.INACTIVE:
            raise LifecycleInvariantError(
                "Only false conditional constraints may be inactive."
            )
        underlying_type = None
        condition_evaluation = None
        parsed = _parse_predicate(constraint_type, predicate)

    if constraint_type is ConstraintType.ASSUMED:
        if status is not ConstraintResolutionStatus.OVERRIDDEN:
            raise LifecycleInvariantError(
                "An assumption reaching validation must be overridden."
            )

    return _ConstraintPolicy(
        constraint_id,
        constraint_type,
        underlying_type,
        status,
        predicate,
        parsed,
        condition_evaluation,
    )


def _packet_policy(request: ValidationRequest) -> _PacketPolicy:
    packet = request.packet
    payload = packet.packet_json
    if (
        packet.schema_version != CONTEXT_PACKET_SCHEMA_VERSION
        or payload["schema_version"] != CONTEXT_PACKET_SCHEMA_VERSION
    ):
        raise LifecycleInvariantError(
            "Response validation requires an mvp-context-packet-v2 packet."
        )

    active_state = _object(payload["active_state"], "packet active state")
    validation = _object(
        payload["validation_context"],
        "packet validation context",
    )
    active_topic_raw = validation["active_topic"]
    active_topic_id: object = None
    topic_terms: tuple[str, ...] = ()
    if active_topic_raw is not None:
        active_topic = _object(active_topic_raw, "packet validation active topic")
        active_topic_id = active_topic["topic_id"]
        raw_terms = _array(active_topic["terms"], "packet active-topic terms")
        if any(not isinstance(term, str) for term in raw_terms):
            raise LifecycleInvariantError(
                "Packet active-topic terms must contain text."
            )
        topic_terms = tuple(term for term in raw_terms if isinstance(term, str))
        if any(
            len(normalize_word_tokens(term)) != 1
            or normalize_words(term) != term
            for term in topic_terms
        ):
            raise LifecycleInvariantError(
                "Packet active-topic terms must be canonical normalized tokens."
            )
    if (active_state["topic_id"] is None) != (active_topic_raw is None) or (
        active_topic_raw is not None
        and active_state["topic_id"] != active_topic_id
    ):
        raise LifecycleInvariantError(
            "Packet active state and validation topic must agree."
        )

    packet_request = _object(payload["request"], "packet request")
    response_policy = _object(payload["response_policy"], "packet response policy")
    shape_rule = _object(
        validation["output_shape_rule"],
        "packet output-shape rule",
    )
    output_values = (
        packet_request["expected_output_type"],
        response_policy["output_type"],
        shape_rule["output_type"],
    )
    if len(set(output_values)) != 1:
        raise LifecycleInvariantError(
            "Packet request, policy, and shape output types must agree."
        )
    output_type = _enum_value(
        OutputType,
        output_values[0],
        "packet response output type",
    )
    assert isinstance(output_type, OutputType)
    if output_type not in _MODEL_OUTPUT_TYPES:
        raise LifecycleInvariantError(
            "Response validation requires a model-eligible output type."
        )

    correction_limit = _uint(
        response_policy["correction_limit"],
        "packet correction limit",
    )
    generation_limit = _uint(
        response_policy["model_generation_limit"],
        "packet model generation limit",
    )
    absolute_cap = _uint(
        response_policy["absolute_model_generation_cap"],
        "packet absolute model generation cap",
    )
    if (
        correction_limit > 2
        or generation_limit != correction_limit + 1
        or absolute_cap != 3
    ):
        raise LifecycleInvariantError(
            "Packet response-policy generation limits are invalid."
        )

    output_shape = _text(shape_rule["shape"], "packet output shape")
    if output_shape not in {
        "NON_EMPTY_TEXT",
        "NUMBERED_LIST",
        "FENCED_CODE",
        "COMPARISON_LIST",
    }:
        raise LifecycleInvariantError("Packet output shape is not canonical.")
    output_shape_rule_id = _text(shape_rule["id"], "packet output-shape rule ID")
    preserve_verb_list_id = _text(
        validation["preserve_change_verb_list_id"],
        "packet preservation verb-list ID",
    )
    preserve_verbs_raw = _array(
        validation["preserve_change_verbs"],
        "packet preservation verbs",
    )
    preserve_verbs = tuple(
        _text(verb, "packet preservation verb") for verb in preserve_verbs_raw
    )
    if not preserve_verbs or any(
        len(normalize_word_tokens(verb)) != 1 or normalize_words(verb) != verb
        for verb in preserve_verbs
    ):
        raise LifecycleInvariantError(
            "Packet preservation verbs must be canonical normalized tokens."
        )
    markers_raw = _array(validation["action_markers"], "packet action markers")
    action_markers = tuple(
        _text(marker, "packet action marker") for marker in markers_raw
    )
    if not action_markers:
        raise LifecycleInvariantError("Packet action markers cannot be empty.")

    constraints = tuple(
        _constraint_policy(raw)
        for raw in _array(payload["constraints"], "packet constraints")
    )
    return _PacketPolicy(
        topic_terms,
        output_type,
        output_shape,
        output_shape_rule_id,
        preserve_verb_list_id,
        preserve_verbs,
        action_markers,
        constraints,
    )


@dataclass(frozen=True, slots=True)
class _Sentence:
    span: SentenceSpan
    tokens: tuple[NormalizedWordToken, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    source: str
    tokens: tuple[NormalizedWordToken, ...]
    sentences: tuple[_Sentence, ...]

    @classmethod
    def from_source(cls, source: str) -> _Candidate:
        spans = split_sentence_spans(source)
        sentences: list[_Sentence] = []
        for span in spans:
            relative_tokens = normalize_word_tokens(
                source[span.source_start : span.source_end]
            )
            sentences.append(
                _Sentence(
                    span,
                    tuple(
                        NormalizedWordToken(
                            token.text,
                            token.source_start + span.source_start,
                            token.source_end + span.source_start,
                        )
                        for token in relative_tokens
                    ),
                )
            )
        return cls(source, normalize_word_tokens(source), tuple(sentences))

    def sentence_ordinal(self, start: int, end: int) -> int | None:
        for sentence in self.sentences:
            if (
                sentence.span.source_start <= start
                and end <= sentence.span.source_end
            ):
                return sentence.span.ordinal
        return None


def _location_sort_key(location: MatchLocation) -> tuple[int, int, int]:
    sentence = -1 if location.sentence_ordinal is None else location.sentence_ordinal
    return location.source_start, location.source_end, sentence


def _canonical_locations(
    locations: list[MatchLocation] | tuple[MatchLocation, ...],
) -> tuple[MatchLocation, ...]:
    return tuple(sorted(set(locations), key=_location_sort_key))


def _sequence_matches(
    sentence: _Sentence,
    phrase: tuple[str, ...],
) -> tuple[MatchLocation, ...]:
    if not phrase or len(phrase) > len(sentence.tokens):
        return ()
    locations: list[MatchLocation] = []
    for start in range(len(sentence.tokens) - len(phrase) + 1):
        selected = sentence.tokens[start : start + len(phrase)]
        if tuple(token.text for token in selected) == phrase:
            locations.append(
                MatchLocation(
                    selected[0].source_start,
                    selected[-1].source_end,
                    sentence.span.ordinal,
                )
            )
    return tuple(locations)


def _exact_matches(
    candidate: _Candidate,
    phrase: tuple[str, ...],
) -> tuple[MatchLocation, ...]:
    locations = [
        location
        for sentence in candidate.sentences
        for location in _sequence_matches(sentence, phrase)
    ]
    return _canonical_locations(locations)


def _action_object_matches(
    candidate: _Candidate,
    action: tuple[str, ...],
    object_value: tuple[str, ...],
) -> tuple[MatchLocation, ...]:
    locations: list[MatchLocation] = []
    for sentence in candidate.sentences:
        action_matches = _sequence_matches(sentence, action)
        object_matches = _sequence_matches(sentence, object_value)
        if action_matches and object_matches:
            locations.extend(action_matches)
            locations.extend(object_matches)
    return _canonical_locations(locations)


def _preservation_matches(
    candidate: _Candidate,
    verbs: tuple[str, ...],
    object_value: tuple[str, ...],
) -> tuple[MatchLocation, ...]:
    locations: list[MatchLocation] = []
    for sentence in candidate.sentences:
        verb_matches = tuple(
            location
            for verb in verbs
            for location in _sequence_matches(sentence, (verb,))
        )
        object_matches = _sequence_matches(sentence, object_value)
        if verb_matches and object_matches:
            locations.extend(verb_matches)
            locations.extend(object_matches)
    return _canonical_locations(locations)


def _literal_matches(
    candidate: _Candidate,
    markers: tuple[str, ...],
) -> tuple[MatchLocation, ...]:
    locations = [
        MatchLocation(start, end, candidate.sentence_ordinal(start, end))
        for marker in markers
        for start, end in find_casefolded_literal_spans(candidate.source, marker)
    ]
    return _canonical_locations(locations)


def _source_lines(source: str) -> tuple[str, ...]:
    return tuple(source.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def _non_empty_lines(source: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in _source_lines(source) if line.strip())


def _substantive(source: str, markers: tuple[str, ...]) -> bool:
    removed: set[int] = set()
    for marker in markers:
        for start, end in find_casefolded_literal_spans(source, marker):
            removed.update(range(start, end))
    without_markers = "".join(
        character for index, character in enumerate(source) if index not in removed
    )
    retained_lines: list[str] = []
    for line in _source_lines(without_markers):
        content = line.lstrip()
        heading = re.match(r"#+(?:\s*)", content)
        if heading is not None:
            content = content[heading.end() :]
        if content.strip():
            retained_lines.append(content)
    return bool(normalize_word_tokens("\n".join(retained_lines)))


def _numbered_item(line: str) -> int | None:
    match = _NUMBERED_ITEM.fullmatch(line)
    return None if match is None else int(match.group(1))


def _shape_passes(
    candidate: _Candidate,
    shape: str,
    markers: tuple[str, ...],
) -> bool:
    if shape == "NON_EMPTY_TEXT":
        return _substantive(candidate.source, markers)

    lines = _non_empty_lines(candidate.source)
    if shape == "NUMBERED_LIST":
        numbers = tuple(_numbered_item(line) for line in lines)
        return bool(lines) and all(number is not None for number in numbers) and (
            numbers == tuple(range(1, len(lines) + 1))
        )

    if shape == "FENCED_CODE":
        if (
            len(lines) < 3
            or _OPENING_FENCE.fullmatch(lines[0]) is None
            or lines[-1] != "```"
        ):
            return False
        if sum(line.count("```") for line in lines) != 2:
            return False
        return any(character.isspace() is False for line in lines[1:-1] for character in line)

    if shape == "COMPARISON_LIST":
        if len(lines) < 2:
            return False
        labels: list[str] = []
        for line in lines:
            match = _COMPARISON_ITEM.fullmatch(line)
            if match is None or ":" not in match.group(1):
                return False
            label, value = match.group(1).split(":", 1)
            label = label.strip()
            value = value.strip()
            normalized_label = normalize_words(label)
            if not label or not value or not normalized_label:
                return False
            labels.append(normalized_label)
        return len(set(labels)) == len(labels)

    raise LifecycleInvariantError("Unknown output-shape predicate.")


def _one_ordered_step(candidate: _Candidate) -> bool:
    lines = _non_empty_lines(candidate.source)
    return len(lines) == 1 and _numbered_item(lines[0]) == 1


def _line_ranges(source: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(source):
        if source[index] in {"\r", "\n"}:
            ranges.append((start, index))
            if (
                source[index] == "\r"
                and index + 1 < len(source)
                and source[index + 1] == "\n"
            ):
                index += 1
            start = index + 1
        index += 1
    ranges.append((start, len(source)))
    return tuple(ranges)


def _repetition_groups(
    candidate: _Candidate,
) -> tuple[tuple[MatchLocation, ...], ...]:
    excluded_lines = tuple(
        (start, end)
        for start, end in _line_ranges(candidate.source)
        if candidate.source.startswith("#", start)
        or candidate.source.startswith("> ", start)
    )
    by_normalized_sentence: dict[tuple[str, ...], list[MatchLocation]] = {}
    for sentence in candidate.sentences:
        if any(
            start <= sentence.span.source_start <= end
            for start, end in excluded_lines
        ):
            continue
        normalized = tuple(token.text for token in sentence.tokens)
        if not normalized:
            continue
        by_normalized_sentence.setdefault(normalized, []).append(
            MatchLocation(
                sentence.span.source_start,
                sentence.span.source_end,
                sentence.span.ordinal,
            )
        )
    groups = [
        _canonical_locations(locations)
        for locations in by_normalized_sentence.values()
        if len(locations) >= 2
    ]
    return tuple(sorted(groups, key=lambda group: group[0].sentence_ordinal or 0))


class _EvidenceCollector:
    def __init__(self, candidate: _Candidate) -> None:
        self._candidate = candidate
        self.evidence: list[ValidationEvidence] = []
        self.violations: list[ValidationViolation] = []

    def add(
        self,
        check_id: ValidationCheckId,
        outcome: ValidationOutcome,
        *,
        rule_id: str | None = None,
        constraint_id: DomainId | None = None,
        predicate: str | None = None,
        topic_terms: tuple[str, ...] = (),
        output_type: OutputType | None = None,
        output_shape: str | None = None,
        matches: tuple[MatchLocation, ...] = (),
        missing_predicate: str | None = None,
        warning_code: ValidationWarningCode | None = None,
    ) -> None:
        violation_code = (
            _VIOLATION_BY_CHECK[check_id]
            if outcome is ValidationOutcome.FAILED
            else None
        )
        severity = {
            ValidationOutcome.FAILED: ValidationSeverity.ERROR,
            ValidationOutcome.WARNING: ValidationSeverity.WARNING,
            ValidationOutcome.PASSED: ValidationSeverity.INFO,
            ValidationOutcome.NOT_APPLICABLE: ValidationSeverity.INFO,
        }[outcome]
        ordinal = len(self.evidence)
        item = ValidationEvidence(
            ordinal,
            check_id,
            rule_id,
            constraint_id,
            severity,
            outcome,
            FrozenJsonObject(
                {
                    "candidate_token_count": len(self._candidate.tokens),
                    "sentence_count": len(self._candidate.sentences),
                    "predicate": predicate,
                    "topic_terms": topic_terms,
                    "output_type": None if output_type is None else output_type.value,
                    "output_shape": output_shape,
                }
            ),
            _canonical_locations(matches),
            missing_predicate,
            violation_code,
            warning_code,
            _EXPLANATION[outcome],
        )
        self.evidence.append(item)
        if violation_code is not None:
            self.violations.append(
                ValidationViolation(
                    len(self.violations),
                    violation_code,
                    validation_violation_message(violation_code),
                    constraint_id,
                    ValidationViolationEvidence(check_id, rule_id, ordinal),
                )
            )


def _positive_matches(
    candidate: _Candidate,
    predicate: _ParsedPredicate,
) -> tuple[bool, tuple[MatchLocation, ...]]:
    if predicate.form == "ordered_step":
        return _one_ordered_step(candidate), ()
    if predicate.form == "exact":
        matches = _exact_matches(candidate, predicate.object_tokens)
    else:
        matches = _action_object_matches(
            candidate,
            predicate.action_tokens,
            predicate.object_tokens,
        )
    return bool(matches), matches


def _hard_matches(
    candidate: _Candidate,
    policy: _PacketPolicy,
    constraint: _ConstraintPolicy,
    effective_type: ConstraintType,
) -> tuple[bool, tuple[MatchLocation, ...]]:
    """Return whether a hard predicate passes and its contributing locations."""

    predicate = constraint.parsed_predicate
    if effective_type is ConstraintType.REQUIRED:
        return _positive_matches(candidate, predicate)
    if effective_type is ConstraintType.FORBIDDEN:
        if constraint.predicate == "MUST_NOT_EXECUTE:IMAGE_OR_ACTION":
            matches = _literal_matches(candidate, policy.action_markers)
        else:
            matches = _action_object_matches(
                candidate,
                predicate.action_tokens,
                predicate.object_tokens,
            )
        return not matches, matches
    if effective_type is ConstraintType.PRESERVE:
        matches = _preservation_matches(
            candidate,
            policy.preserve_verbs,
            predicate.object_tokens,
        )
        return not matches, matches
    raise LifecycleInvariantError("A hard predicate has an invalid effective type.")


class DeterministicResponseValidator:
    """Validate a candidate solely from its immutable packet snapshot."""

    def validate(self, request: ValidationRequest) -> ValidationResult:
        if not isinstance(request, ValidationRequest):
            raise LifecycleInvariantError(
                "Response validation requires a typed ValidationRequest."
            )

        # Packet integrity is deliberately established before candidate inspection.
        try:
            policy = _packet_policy(request)
        except LifecycleInvariantError:
            raise
        except (DomainValidationError, KeyError, TypeError, ValueError) as error:
            raise LifecycleInvariantError(
                "Response validation requires a canonical immutable context packet."
            ) from error
        candidate = _Candidate.from_source(request.candidate_response)
        collector = _EvidenceCollector(candidate)

        topic_locations = _canonical_locations(
            [
                MatchLocation(
                    token.source_start,
                    token.source_end,
                    sentence.span.ordinal,
                )
                for sentence in candidate.sentences
                for token in sentence.tokens
                if token.text in policy.topic_terms
            ]
        )
        if not policy.topic_terms:
            collector.add(
                ValidationCheckId.TOPIC,
                ValidationOutcome.NOT_APPLICABLE,
                topic_terms=policy.topic_terms,
            )
        elif topic_locations:
            collector.add(
                ValidationCheckId.TOPIC,
                ValidationOutcome.PASSED,
                topic_terms=policy.topic_terms,
                matches=topic_locations,
            )
        else:
            collector.add(
                ValidationCheckId.TOPIC,
                ValidationOutcome.FAILED,
                topic_terms=policy.topic_terms,
                missing_predicate="ANY_ACTIVE_TOPIC_TERM",
            )

        shape_passed = _shape_passes(
            candidate,
            policy.output_shape,
            policy.action_markers,
        )
        collector.add(
            ValidationCheckId.OUTPUT_SHAPE,
            ValidationOutcome.PASSED if shape_passed else ValidationOutcome.FAILED,
            rule_id=policy.output_shape_rule_id,
            output_type=policy.output_type,
            output_shape=policy.output_shape,
        )

        marker_locations = _literal_matches(candidate, policy.action_markers)
        collector.add(
            ValidationCheckId.ACTION_MARKER,
            (
                ValidationOutcome.FAILED
                if marker_locations
                else ValidationOutcome.PASSED
            ),
            matches=marker_locations,
        )

        check_types = (
            (ValidationCheckId.REQUIRED_CONSTRAINT, ConstraintType.REQUIRED),
            (ValidationCheckId.FORBIDDEN_CONSTRAINT, ConstraintType.FORBIDDEN),
            (ValidationCheckId.PRESERVE_CONSTRAINT, ConstraintType.PRESERVE),
        )
        for check_id, constraint_type in check_types:
            for constraint in policy.constraints:
                if constraint.constraint_type is not constraint_type:
                    continue
                rule_id = (
                    policy.preserve_verb_list_id
                    if constraint_type is ConstraintType.PRESERVE
                    else None
                )
                if constraint.status is not ConstraintResolutionStatus.ACTIVE:
                    collector.add(
                        check_id,
                        ValidationOutcome.NOT_APPLICABLE,
                        rule_id=rule_id,
                        constraint_id=constraint.id,
                        predicate=constraint.predicate,
                    )
                    continue
                passed, matches = _hard_matches(
                    candidate,
                    policy,
                    constraint,
                    constraint_type,
                )
                collector.add(
                    check_id,
                    ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
                    rule_id=rule_id,
                    constraint_id=constraint.id,
                    predicate=constraint.predicate,
                    matches=matches,
                    missing_predicate=(
                        constraint.predicate
                        if not passed and constraint_type is ConstraintType.REQUIRED
                        else None
                    ),
                )

        for constraint in policy.constraints:
            if constraint.constraint_type is not ConstraintType.CONDITIONAL:
                continue
            rule_id = (
                policy.preserve_verb_list_id
                if constraint.underlying_type is ConstraintType.PRESERVE
                else None
            )
            if constraint.status is not ConstraintResolutionStatus.ACTIVE:
                collector.add(
                    ValidationCheckId.CONDITIONAL_CONSTRAINT,
                    ValidationOutcome.NOT_APPLICABLE,
                    rule_id=rule_id,
                    constraint_id=constraint.id,
                    predicate=constraint.predicate,
                )
                continue
            if constraint.condition_evaluation is not ConditionEvaluation.TRUE:
                raise LifecycleInvariantError(
                    "An active conditional constraint must evaluate true."
                )
            assert constraint.underlying_type is not None
            passed, matches = _hard_matches(
                candidate,
                policy,
                constraint,
                constraint.underlying_type,
            )
            collector.add(
                ValidationCheckId.CONDITIONAL_CONSTRAINT,
                ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
                rule_id=rule_id,
                constraint_id=constraint.id,
                predicate=constraint.predicate,
                matches=matches,
                missing_predicate=(
                    constraint.predicate
                    if not passed
                    and constraint.underlying_type is ConstraintType.REQUIRED
                    else None
                ),
            )

        soft_checks = (
            (
                ValidationCheckId.PREFERRED_CONSTRAINT,
                ConstraintType.PREFERRED,
                ValidationWarningCode.PREFERRED_CONSTRAINT_UNSATISFIED,
            ),
            (
                ValidationCheckId.OPTIONAL_CONSTRAINT,
                ConstraintType.OPTIONAL,
                ValidationWarningCode.OPTIONAL_CONSTRAINT_UNSATISFIED,
            ),
        )
        for check_id, constraint_type, warning_code in soft_checks:
            for constraint in policy.constraints:
                if constraint.constraint_type is not constraint_type:
                    continue
                if constraint.status is not ConstraintResolutionStatus.ACTIVE:
                    collector.add(
                        check_id,
                        ValidationOutcome.NOT_APPLICABLE,
                        constraint_id=constraint.id,
                        predicate=constraint.predicate,
                    )
                    continue
                passed, matches = _positive_matches(
                    candidate,
                    constraint.parsed_predicate,
                )
                collector.add(
                    check_id,
                    ValidationOutcome.PASSED if passed else ValidationOutcome.WARNING,
                    constraint_id=constraint.id,
                    predicate=constraint.predicate,
                    matches=matches,
                    missing_predicate=None if passed else constraint.predicate,
                    warning_code=None if passed else warning_code,
                )

        for constraint in policy.constraints:
            if constraint.constraint_type is ConstraintType.ASSUMED:
                collector.add(
                    ValidationCheckId.ASSUMED_CONSTRAINT,
                    ValidationOutcome.WARNING,
                    constraint_id=constraint.id,
                    predicate=constraint.predicate,
                    warning_code=ValidationWarningCode.ASSUMED_CONSTRAINT_NON_BINDING,
                )

        repetition_groups = _repetition_groups(candidate)
        if repetition_groups:
            for locations in repetition_groups:
                collector.add(
                    ValidationCheckId.REPETITION,
                    ValidationOutcome.WARNING,
                    matches=locations,
                    warning_code=ValidationWarningCode.UNNECESSARY_REPETITION,
                )
        else:
            collector.add(
                ValidationCheckId.REPETITION,
                ValidationOutcome.PASSED,
            )

        violations = tuple(collector.violations)
        evidence = tuple(collector.evidence)
        return ValidationResult(
            request.validation_result_id,
            request.model_response_id,
            ValidationStatus.FAILED if violations else ValidationStatus.PASSED,
            calculate_validation_score(violations, evidence),
            violations,
            evidence,
            request.created_at,
        )


__all__ = ["DeterministicResponseValidator"]
