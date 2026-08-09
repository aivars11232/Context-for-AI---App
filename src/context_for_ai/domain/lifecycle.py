"""Immutable records for processing, model, validation, and failure lineage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import unicodedata

from context_for_ai.domain.enums import (
    ClarificationReason,
    FailureCode,
    ModelRequestPurpose,
    ModelRequestStatus,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
    ProviderKind,
    ValidationCheckId,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
    ValidationViolationCode,
    ValidationWarningCode,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _optional_text(field_name: str, value: str | None) -> None:
    if value is not None:
        _required_text(field_name, value)


def _normalize_time(instance: object, field_name: str) -> datetime:
    value = ensure_utc(getattr(instance, field_name))
    object.__setattr__(instance, field_name, value)
    return value


def _normalize_optional_time(instance: object, field_name: str) -> datetime | None:
    raw_value = getattr(instance, field_name)
    if raw_value is None:
        return None
    value = ensure_utc(raw_value)
    object.__setattr__(instance, field_name, value)
    return value


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be a non-negative integer.")


def _freeze_json_object(value: FrozenJsonObject | Mapping[str, object]) -> FrozenJsonObject:
    return value if isinstance(value, FrozenJsonObject) else FrozenJsonObject(value)


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    id: DomainId
    conversation_id: DomainId
    user_message_id: DomainId
    idempotency_key: str
    status: ProcessingRunStatus
    state_version_at_start: int
    configuration_fingerprint: str
    started_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _required_text("ProcessingRun.idempotency_key", self.idempotency_key)
        _non_negative_integer(
            "ProcessingRun.state_version_at_start",
            self.state_version_at_start,
        )
        _required_text(
            "ProcessingRun.configuration_fingerprint",
            self.configuration_fingerprint,
        )
        _normalize_time(self, "started_at")
        _normalize_optional_time(self, "completed_at")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    id: DomainId
    processing_run_id: DomainId
    context_packet_id: DomainId
    purpose: ModelRequestPurpose
    attempt_number: int
    provider: ProviderKind
    model_name: str
    status: ModelRequestStatus
    rendered_prompt: str
    request: FrozenJsonObject
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None

    def __post_init__(self) -> None:
        _non_negative_integer("ModelRequest.attempt_number", self.attempt_number)
        if self.attempt_number > 2:
            raise LifecycleInvariantError("ModelRequest.attempt_number cannot exceed 2.")
        _required_text("ModelRequest.model_name", self.model_name)
        if not isinstance(self.rendered_prompt, str):
            raise LifecycleInvariantError("ModelRequest.rendered_prompt must be text.")
        object.__setattr__(self, "request", _freeze_json_object(self.request))
        _normalize_optional_time(self, "started_at")
        _normalize_optional_time(self, "completed_at")
        _optional_text("ModelRequest.error_code", self.error_code)
        _optional_text("ModelRequest.safe_error_message", self.safe_error_message)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    id: DomainId
    model_request_id: DomainId
    response_text: str
    metadata: FrozenJsonObject
    assistant_message_id: DomainId | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.response_text, str):
            raise LifecycleInvariantError("ModelResponse.response_text must be text.")
        object.__setattr__(self, "metadata", _freeze_json_object(self.metadata))
        _normalize_time(self, "created_at")


_VALIDATION_VIOLATION_MESSAGES = {
    ValidationViolationCode.TOPIC_MISMATCH:
        "The response does not reference the active topic.",
    ValidationViolationCode.OUTPUT_TYPE_MISMATCH:
        "The response does not satisfy the required text output policy.",
    ValidationViolationCode.MISSING_REQUIREMENT:
        "The response does not satisfy a required constraint.",
    ValidationViolationCode.FORBIDDEN_ACTION:
        "The response contains a forbidden action or object.",
    ValidationViolationCode.PRESERVATION_VIOLATION:
        "The response describes a forbidden change to preserved content.",
    ValidationViolationCode.CONDITIONAL_VIOLATION:
        "The response does not satisfy an active conditional constraint.",
}

_VALIDATION_EXPLANATIONS = {
    ValidationOutcome.PASSED: "The deterministic predicate passed.",
    ValidationOutcome.FAILED: "The deterministic predicate failed.",
    ValidationOutcome.WARNING: "A non-failing deterministic warning was recorded.",
    ValidationOutcome.NOT_APPLICABLE: "The check is not applicable to this packet.",
}
_VALIDATION_NORMALIZED_INPUT_KEYS = frozenset(
    {
        "candidate_token_count",
        "sentence_count",
        "predicate",
        "topic_terms",
        "output_type",
        "output_shape",
    }
)
_VALIDATION_OUTPUT_SHAPES = frozenset(
    {"NON_EMPTY_TEXT", "NUMBERED_LIST", "FENCED_CODE", "COMPARISON_LIST"}
)
_MODEL_OUTPUT_TYPES = frozenset(
    output_type
    for output_type in OutputType
    if output_type not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
)
_CONSTRAINT_CHECKS = frozenset(
    {
        ValidationCheckId.REQUIRED_CONSTRAINT,
        ValidationCheckId.FORBIDDEN_CONSTRAINT,
        ValidationCheckId.PRESERVE_CONSTRAINT,
        ValidationCheckId.CONDITIONAL_CONSTRAINT,
        ValidationCheckId.PREFERRED_CONSTRAINT,
        ValidationCheckId.OPTIONAL_CONSTRAINT,
        ValidationCheckId.ASSUMED_CONSTRAINT,
    }
)
_FAILED_CODE_BY_CHECK = {
    ValidationCheckId.TOPIC: ValidationViolationCode.TOPIC_MISMATCH,
    ValidationCheckId.OUTPUT_SHAPE: ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
    ValidationCheckId.ACTION_MARKER: ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
    ValidationCheckId.REQUIRED_CONSTRAINT: ValidationViolationCode.MISSING_REQUIREMENT,
    ValidationCheckId.FORBIDDEN_CONSTRAINT: ValidationViolationCode.FORBIDDEN_ACTION,
    ValidationCheckId.PRESERVE_CONSTRAINT: ValidationViolationCode.PRESERVATION_VIOLATION,
    ValidationCheckId.CONDITIONAL_CONSTRAINT: ValidationViolationCode.CONDITIONAL_VIOLATION,
}
_WARNING_CODE_BY_CHECK = {
    ValidationCheckId.PREFERRED_CONSTRAINT:
        ValidationWarningCode.PREFERRED_CONSTRAINT_UNSATISFIED,
    ValidationCheckId.OPTIONAL_CONSTRAINT:
        ValidationWarningCode.OPTIONAL_CONSTRAINT_UNSATISFIED,
    ValidationCheckId.ASSUMED_CONSTRAINT:
        ValidationWarningCode.ASSUMED_CONSTRAINT_NON_BINDING,
    ValidationCheckId.REPETITION: ValidationWarningCode.UNNECESSARY_REPETITION,
}
_HARD_VIOLATION_CODES = frozenset(
    {
        ValidationViolationCode.MISSING_REQUIREMENT,
        ValidationViolationCode.FORBIDDEN_ACTION,
        ValidationViolationCode.PRESERVATION_VIOLATION,
        ValidationViolationCode.CONDITIONAL_VIOLATION,
    }
)
_TOPIC_OR_OUTPUT_VIOLATION_CODES = frozenset(
    {
        ValidationViolationCode.TOPIC_MISMATCH,
        ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
    }
)
_VALIDATION_SCORE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def validation_violation_message(code: ValidationViolationCode) -> str:
    """Return the fixed public message for one candidate-failing code."""

    if not isinstance(code, ValidationViolationCode):
        raise LifecycleInvariantError("Validation violation code must be canonical.")
    return _VALIDATION_VIOLATION_MESSAGES[code]


@dataclass(frozen=True, slots=True)
class MatchLocation:
    """One source-mapped match without copied candidate content."""

    source_start: int
    source_end: int
    sentence_ordinal: int | None

    def __post_init__(self) -> None:
        _non_negative_integer("MatchLocation.source_start", self.source_start)
        if (
            not isinstance(self.source_end, int)
            or isinstance(self.source_end, bool)
            or self.source_end <= self.source_start
        ):
            raise LifecycleInvariantError(
                "MatchLocation.source_end must be greater than source_start."
            )
        if self.sentence_ordinal is not None:
            _non_negative_integer(
                "MatchLocation.sentence_ordinal",
                self.sentence_ordinal,
            )

    def to_json_object(self) -> FrozenJsonObject:
        return FrozenJsonObject(
            {
                "source_start": self.source_start,
                "source_end": self.source_end,
                "sentence_ordinal": self.sentence_ordinal,
            }
        )


def _normalized_topic_term(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == unicodedata.normalize("NFC", value).casefold()
        and not any(character.isspace() for character in value)
        and not any(
            unicodedata.category(character).startswith("P") for character in value
        )
    )


def _validate_normalized_input(
    check_id: ValidationCheckId,
    value: FrozenJsonObject,
) -> None:
    if frozenset(value) != _VALIDATION_NORMALIZED_INPUT_KEYS:
        raise LifecycleInvariantError(
            "ValidationEvidence.normalized_input must have the exact canonical fields."
        )
    for field_name in ("candidate_token_count", "sentence_count"):
        _non_negative_integer(
            f"ValidationEvidence.normalized_input.{field_name}",
            value[field_name],  # type: ignore[arg-type]
        )

    predicate = value["predicate"]
    topic_terms = value["topic_terms"]
    output_type = value["output_type"]
    output_shape = value["output_shape"]
    _optional_text("ValidationEvidence.normalized_input.predicate", predicate)  # type: ignore[arg-type]
    if not isinstance(topic_terms, tuple) or any(
        not _normalized_topic_term(term) for term in topic_terms
    ):
        raise LifecycleInvariantError(
            "ValidationEvidence topic_terms must be normalized tokens."
        )

    if check_id is ValidationCheckId.TOPIC:
        if predicate is not None or output_type is not None or output_shape is not None:
            raise LifecycleInvariantError(
                "TOPIC evidence may contain only topic normalization policy."
            )
    elif topic_terms:
        raise LifecycleInvariantError(
            "Only TOPIC evidence may contain topic terms."
        )

    if check_id is ValidationCheckId.OUTPUT_SHAPE:
        try:
            canonical_output_type = OutputType(output_type)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise LifecycleInvariantError(
                "OUTPUT_SHAPE evidence requires a canonical output type."
            ) from error
        if canonical_output_type not in _MODEL_OUTPUT_TYPES:
            raise LifecycleInvariantError(
                "OUTPUT_SHAPE evidence requires a model-eligible output type."
            )
        if output_shape not in _VALIDATION_OUTPUT_SHAPES or predicate is not None:
            raise LifecycleInvariantError(
                "OUTPUT_SHAPE evidence requires one canonical shape."
            )
    elif output_type is not None or output_shape is not None:
        raise LifecycleInvariantError(
            "Only OUTPUT_SHAPE evidence may contain output policy fields."
        )

    if check_id in _CONSTRAINT_CHECKS:
        if predicate is None:
            raise LifecycleInvariantError(
                "Constraint evidence requires its exact predicate."
            )
    elif predicate is not None:
        raise LifecycleInvariantError(
            "Only constraint evidence may contain a predicate."
        )


def _location_sort_key(location: MatchLocation) -> tuple[int, int, int]:
    sentence = -1 if location.sentence_ordinal is None else location.sentence_ordinal
    return location.source_start, location.source_end, sentence


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    """One exact deterministic check result retained in the validation report."""

    ordinal: int
    check_id: ValidationCheckId
    rule_id: str | None
    constraint_id: DomainId | None
    severity: ValidationSeverity
    outcome: ValidationOutcome
    normalized_input: FrozenJsonObject
    matches: tuple[MatchLocation, ...]
    missing_predicate: str | None
    violation_code: ValidationViolationCode | None
    warning_code: ValidationWarningCode | None
    explanation: str

    def __post_init__(self) -> None:
        _non_negative_integer("ValidationEvidence.ordinal", self.ordinal)
        if not isinstance(self.check_id, ValidationCheckId):
            raise LifecycleInvariantError("ValidationEvidence.check_id must be canonical.")
        if not isinstance(self.severity, ValidationSeverity) or not isinstance(
            self.outcome, ValidationOutcome
        ):
            raise LifecycleInvariantError(
                "ValidationEvidence severity and outcome must be canonical."
            )
        _optional_text("ValidationEvidence.rule_id", self.rule_id)
        _optional_text("ValidationEvidence.missing_predicate", self.missing_predicate)

        if self.check_id in _CONSTRAINT_CHECKS:
            if not isinstance(self.constraint_id, DomainId):
                raise LifecycleInvariantError(
                    "Constraint evidence requires a constraint domain ID."
                )
        elif self.constraint_id is not None:
            raise LifecycleInvariantError(
                "Non-constraint evidence requires a null constraint ID."
            )

        normalized_input = _freeze_json_object(self.normalized_input)
        _validate_normalized_input(self.check_id, normalized_input)
        object.__setattr__(self, "normalized_input", normalized_input)
        predicate = normalized_input["predicate"]

        requires_rule_id = self.check_id in {
            ValidationCheckId.OUTPUT_SHAPE,
            ValidationCheckId.PRESERVE_CONSTRAINT,
        } or (
            self.check_id is ValidationCheckId.CONDITIONAL_CONSTRAINT
            and isinstance(predicate, str)
            and predicate.startswith("MUST_PRESERVE:")
        )
        if requires_rule_id:
            if self.rule_id is None:
                raise LifecycleInvariantError(
                    "Output-shape and preservation evidence require a rule ID."
                )
        elif self.rule_id is not None:
            raise LifecycleInvariantError(
                "This validation check requires a null rule ID."
            )

        matches = tuple(self.matches)
        if any(not isinstance(match, MatchLocation) for match in matches):
            raise LifecycleInvariantError(
                "ValidationEvidence.matches must contain typed locations."
            )
        if matches != tuple(sorted(matches, key=_location_sort_key)) or len(
            set(matches)
        ) != len(matches):
            raise LifecycleInvariantError(
                "ValidationEvidence.matches must be sorted and deduplicated."
            )
        permits_uncontained_marker = (
            self.check_id is ValidationCheckId.ACTION_MARKER
            or (
                predicate == "MUST_NOT_EXECUTE:IMAGE_OR_ACTION"
                and self.check_id
                in {
                    ValidationCheckId.FORBIDDEN_CONSTRAINT,
                    ValidationCheckId.CONDITIONAL_CONSTRAINT,
                }
            )
        )
        if not permits_uncontained_marker and any(
            match.sentence_ordinal is None for match in matches
        ):
            raise LifecycleInvariantError(
                "Only literal action-marker matches may have a null sentence ordinal."
            )
        object.__setattr__(self, "matches", matches)

        if self.explanation != _VALIDATION_EXPLANATIONS[self.outcome]:
            raise LifecycleInvariantError(
                "ValidationEvidence.explanation must match its outcome."
            )
        if self.outcome is ValidationOutcome.FAILED:
            if (
                self.severity is not ValidationSeverity.ERROR
                or self.warning_code is not None
                or self.violation_code != _FAILED_CODE_BY_CHECK.get(self.check_id)
            ):
                raise LifecycleInvariantError(
                    "FAILED evidence requires its canonical error code."
                )
        elif self.outcome is ValidationOutcome.WARNING:
            if (
                self.severity is not ValidationSeverity.WARNING
                or self.violation_code is not None
                or self.warning_code != _WARNING_CODE_BY_CHECK.get(self.check_id)
            ):
                raise LifecycleInvariantError(
                    "WARNING evidence requires its canonical warning code."
                )
        elif (
            self.severity is not ValidationSeverity.INFO
            or self.violation_code is not None
            or self.warning_code is not None
        ):
            raise LifecycleInvariantError(
                "PASSED and NOT_APPLICABLE evidence must be informational."
            )

        expected_missing: str | None = None
        if self.outcome is ValidationOutcome.FAILED:
            if self.check_id is ValidationCheckId.TOPIC:
                expected_missing = "ANY_ACTIVE_TOPIC_TERM"
            elif self.check_id is ValidationCheckId.REQUIRED_CONSTRAINT:
                expected_missing = predicate if isinstance(predicate, str) else None
            elif (
                self.check_id is ValidationCheckId.CONDITIONAL_CONSTRAINT
                and isinstance(predicate, str)
                and predicate.startswith("MUST_")
                and not predicate.startswith(("MUST_NOT_", "MUST_PRESERVE:"))
            ):
                expected_missing = predicate
        elif self.outcome is ValidationOutcome.WARNING and self.check_id in {
            ValidationCheckId.PREFERRED_CONSTRAINT,
            ValidationCheckId.OPTIONAL_CONSTRAINT,
        }:
            expected_missing = predicate if isinstance(predicate, str) else None
        if self.missing_predicate != expected_missing:
            raise LifecycleInvariantError(
                "ValidationEvidence.missing_predicate is not canonical."
            )

        if self.outcome is ValidationOutcome.NOT_APPLICABLE and matches:
            raise LifecycleInvariantError(
                "NOT_APPLICABLE evidence cannot contain matches."
            )
        if self.check_id is ValidationCheckId.OUTPUT_SHAPE and matches:
            raise LifecycleInvariantError("OUTPUT_SHAPE evidence cannot contain matches.")
        if predicate == "MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME" and matches:
            raise LifecycleInvariantError(
                "The structural one-step predicate cannot contain matches."
            )
        if self.check_id is ValidationCheckId.ASSUMED_CONSTRAINT and matches:
            raise LifecycleInvariantError("ASSUMED evidence cannot contain matches.")
        if self.check_id is ValidationCheckId.REPETITION:
            if self.outcome is ValidationOutcome.WARNING and len(matches) < 2:
                raise LifecycleInvariantError(
                    "A repetition warning requires at least two locations."
                )
            if self.outcome is ValidationOutcome.PASSED and matches:
                raise LifecycleInvariantError(
                    "A repetition pass cannot contain matches."
                )

    def to_json_object(self) -> FrozenJsonObject:
        return FrozenJsonObject(
            {
                "ordinal": self.ordinal,
                "check_id": self.check_id.value,
                "rule_id": self.rule_id,
                "constraint_id": (
                    None if self.constraint_id is None else str(self.constraint_id)
                ),
                "severity": self.severity.value,
                "outcome": self.outcome.value,
                "normalized_input": self.normalized_input,
                "matches": tuple(match.to_json_object() for match in self.matches),
                "missing_predicate": self.missing_predicate,
                "violation_code": (
                    None if self.violation_code is None else self.violation_code.value
                ),
                "warning_code": (
                    None if self.warning_code is None else self.warning_code.value
                ),
                "explanation": self.explanation,
            }
        )


@dataclass(frozen=True, slots=True)
class ValidationViolationEvidence:
    """Closed compact evidence link permitted in a correction envelope."""

    check_id: ValidationCheckId
    rule_id: str | None
    evidence_ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, ValidationCheckId):
            raise LifecycleInvariantError(
                "ValidationViolationEvidence.check_id must be canonical."
            )
        _optional_text("ValidationViolationEvidence.rule_id", self.rule_id)
        _non_negative_integer(
            "ValidationViolationEvidence.evidence_ordinal",
            self.evidence_ordinal,
        )
        if self.check_id in {
            ValidationCheckId.OUTPUT_SHAPE,
            ValidationCheckId.PRESERVE_CONSTRAINT,
        }:
            if self.rule_id is None:
                raise LifecycleInvariantError(
                    "Output-shape and preservation violation evidence require a rule ID."
                )
        elif (
            self.check_id is not ValidationCheckId.CONDITIONAL_CONSTRAINT
            and self.rule_id is not None
        ):
            raise LifecycleInvariantError(
                "This violation evidence requires a null rule ID."
            )

    def to_json_object(self) -> FrozenJsonObject:
        return FrozenJsonObject(
            {
                "check_id": self.check_id.value,
                "rule_id": self.rule_id,
                "evidence_ordinal": self.evidence_ordinal,
            }
        )


@dataclass(frozen=True, slots=True)
class ValidationViolation:
    """One exact candidate-failing violation used as correction data."""

    ordinal: int
    code: ValidationViolationCode
    message: str
    constraint_id: DomainId | None
    evidence: ValidationViolationEvidence

    def __post_init__(self) -> None:
        _non_negative_integer("ValidationViolation.ordinal", self.ordinal)
        if not isinstance(self.code, ValidationViolationCode):
            raise LifecycleInvariantError(
                "ValidationViolation.code must be canonical."
            )
        expected_message = _VALIDATION_VIOLATION_MESSAGES[self.code]
        if self.message != expected_message:
            raise LifecycleInvariantError(
                "ValidationViolation.message must equal the canonical code message."
            )
        if not isinstance(self.evidence, ValidationViolationEvidence):
            raise LifecycleInvariantError(
                "ValidationViolation.evidence must be compact typed evidence."
            )
        if self.constraint_id is not None and not isinstance(
            self.constraint_id, DomainId
        ):
            raise LifecycleInvariantError(
                "ValidationViolation.constraint_id must be a domain ID or null."
            )
        expected_code = _FAILED_CODE_BY_CHECK.get(self.evidence.check_id)
        if expected_code is None or self.code is not expected_code:
            raise LifecycleInvariantError(
                "ValidationViolation code must match its evidence check."
            )
        if self.evidence.check_id in _CONSTRAINT_CHECKS:
            if self.constraint_id is None:
                raise LifecycleInvariantError(
                    "Constraint violations require a constraint ID."
                )
        elif self.constraint_id is not None:
            raise LifecycleInvariantError(
                "Non-constraint violations require a null constraint ID."
            )

    def to_json_object(self) -> FrozenJsonObject:
        return FrozenJsonObject(
            {
                "ordinal": self.ordinal,
                "code": self.code.value,
                "message": self.message,
                "constraint_id": (
                    None if self.constraint_id is None else str(self.constraint_id)
                ),
                "evidence": self.evidence.to_json_object(),
            }
        )


def calculate_validation_score(
    violations: tuple[ValidationViolation, ...],
    evidence: tuple[ValidationEvidence, ...],
) -> UnitScore:
    """Calculate the exact context-independent validation score."""

    hard_count = sum(
        violation.code in _HARD_VIOLATION_CODES for violation in violations
    )
    topic_or_output_count = sum(
        violation.code in _TOPIC_OR_OUTPUT_VIOLATION_CODES
        for violation in violations
    )
    repetition_count = sum(
        item.warning_code is ValidationWarningCode.UNNECESSARY_REPETITION
        for item in evidence
    )
    with localcontext(_VALIDATION_SCORE_CONTEXT):
        score = max(
            Decimal("0.00"),
            Decimal("1.00")
            - Decimal("0.30") * hard_count
            - Decimal("0.15") * topic_or_output_count
            - Decimal("0.05") * repetition_count,
        )
    return UnitScore(score)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    id: DomainId
    model_response_id: DomainId
    status: ValidationStatus
    score: UnitScore
    violations: tuple[ValidationViolation, ...]
    evidence: tuple[ValidationEvidence, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, DomainId) or not isinstance(
            self.model_response_id, DomainId
        ):
            raise LifecycleInvariantError(
                "ValidationResult IDs must be domain IDs."
            )
        if self.status not in {ValidationStatus.PASSED, ValidationStatus.FAILED}:
            raise LifecycleInvariantError(
                "ValidationResult status must be PASSED or FAILED."
            )
        if not isinstance(self.score, UnitScore):
            raise LifecycleInvariantError("ValidationResult.score must be a unit score.")

        violations = tuple(self.violations)
        evidence = tuple(self.evidence)
        if any(not isinstance(item, ValidationViolation) for item in violations):
            raise LifecycleInvariantError(
                "ValidationResult violations must be typed."
            )
        if not evidence or any(
            not isinstance(item, ValidationEvidence) for item in evidence
        ):
            raise LifecycleInvariantError(
                "ValidationResult requires typed evidence."
            )
        if [item.ordinal for item in evidence] != list(range(len(evidence))):
            raise LifecycleInvariantError(
                "ValidationResult evidence requires contiguous zero-based order."
            )
        check_order = {check: index for index, check in enumerate(ValidationCheckId)}
        if tuple(check_order[item.check_id] for item in evidence) != tuple(
            sorted(check_order[item.check_id] for item in evidence)
        ):
            raise LifecycleInvariantError(
                "ValidationResult evidence requires canonical check order."
            )
        for fixed_check in (
            ValidationCheckId.TOPIC,
            ValidationCheckId.OUTPUT_SHAPE,
            ValidationCheckId.ACTION_MARKER,
        ):
            if sum(item.check_id is fixed_check for item in evidence) != 1:
                raise LifecycleInvariantError(
                    "ValidationResult requires one item for every fixed check."
                )
        repetition = tuple(
            item for item in evidence if item.check_id is ValidationCheckId.REPETITION
        )
        if not repetition or (
            any(item.outcome is ValidationOutcome.WARNING for item in repetition)
            and any(item.outcome is ValidationOutcome.PASSED for item in repetition)
        ) or (
            not any(item.outcome is ValidationOutcome.WARNING for item in repetition)
            and not (
                len(repetition) == 1
                and repetition[0].outcome is ValidationOutcome.PASSED
            )
        ):
            raise LifecycleInvariantError(
                "ValidationResult repetition evidence is not canonical."
            )
        constraint_ids = tuple(
            item.constraint_id
            for item in evidence
            if item.constraint_id is not None
        )
        if len(set(constraint_ids)) != len(constraint_ids):
            raise LifecycleInvariantError(
                "ValidationResult requires one evidence item per constraint."
            )
        count_pairs = {
            (
                item.normalized_input["candidate_token_count"],
                item.normalized_input["sentence_count"],
            )
            for item in evidence
        }
        if len(count_pairs) != 1:
            raise LifecycleInvariantError(
                "ValidationResult evidence must share candidate normalization counts."
            )

        if [item.ordinal for item in violations] != list(range(len(violations))):
            raise LifecycleInvariantError(
                "ValidationResult violations require contiguous zero-based order."
            )
        failed_evidence = tuple(
            item for item in evidence if item.outcome is ValidationOutcome.FAILED
        )
        if len(failed_evidence) != len(violations):
            raise LifecycleInvariantError(
                "Every failed evidence item requires exactly one violation."
            )
        for violation, item in zip(violations, failed_evidence, strict=True):
            if (
                violation.code is not item.violation_code
                or violation.constraint_id != item.constraint_id
                or violation.evidence.check_id is not item.check_id
                or violation.evidence.rule_id != item.rule_id
                or violation.evidence.evidence_ordinal != item.ordinal
            ):
                raise LifecycleInvariantError(
                    "ValidationResult violation evidence linkage is not canonical."
                )
        expected_status = (
            ValidationStatus.FAILED if violations else ValidationStatus.PASSED
        )
        if self.status is not expected_status:
            raise LifecycleInvariantError(
                "ValidationResult status must follow its violations."
            )
        if self.score != calculate_validation_score(violations, evidence):
            raise LifecycleInvariantError(
                "ValidationResult score must equal the canonical exact score."
            )

        object.__setattr__(self, "violations", violations)
        object.__setattr__(self, "evidence", evidence)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class CorrectionAttempt:
    id: DomainId
    processing_run_id: DomainId
    attempt_number: int
    prior_model_response_id: DomainId
    revised_model_request_id: DomainId
    reasons: tuple[ValidationViolation, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.attempt_number not in (1, 2):
            raise LifecycleInvariantError(
                "CorrectionAttempt.attempt_number must be 1 or 2."
            )
        reasons = tuple(self.reasons)
        if not reasons or any(
            not isinstance(reason, ValidationViolation) for reason in reasons
        ):
            raise LifecycleInvariantError("CorrectionAttempt.reasons cannot be empty.")
        if [reason.ordinal for reason in reasons] != list(range(len(reasons))):
            raise LifecycleInvariantError(
                "CorrectionAttempt.reasons require contiguous zero-based order."
            )
        object.__setattr__(self, "reasons", reasons)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    id: DomainId
    processing_run_id: DomainId
    reason: ClarificationReason
    question_text: str
    details: FrozenJsonObject
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("ClarificationRequest.question_text", self.question_text)
        object.__setattr__(self, "details", _freeze_json_object(self.details))
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class SafeFailure:
    id: DomainId
    processing_run_id: DomainId
    stage: PipelineStage
    error_code: FailureCode
    safe_message: str
    details: FrozenJsonObject
    is_terminal: bool
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("SafeFailure.safe_message", self.safe_message)
        object.__setattr__(self, "details", _freeze_json_object(self.details))
        if not isinstance(self.is_terminal, bool):
            raise LifecycleInvariantError("SafeFailure.is_terminal must be boolean.")
        _normalize_time(self, "created_at")
