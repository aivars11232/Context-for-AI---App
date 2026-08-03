"""Deterministic constraint extraction and resolution for TASK-0007."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import re

from context_for_ai.context_engine.normalization import (
    normalize_capture,
    normalize_phrase,
    predicate_atom,
    split_action_object,
)
from context_for_ai.domain.decisions import (
    CONDITION_GRAMMAR_VERSION,
    Condition,
    Constraint,
    ConstraintConflictGroup,
    ConstraintDecision,
    ConstraintSourceEvidence,
    ResponsePolicy,
)
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConditionEvaluation,
    ConditionKind,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import PriorityBand, require_priority_band
from context_for_ai.domain.ports.configuration import ContextSettings
from context_for_ai.domain.ports.context import ConstraintEvaluationRequest
from context_for_ai.domain.ports.system import IdGenerator
from context_for_ai.domain.value_objects import FrozenJsonObject, UnitScore


_HARD_TYPES = frozenset(
    {ConstraintType.REQUIRED, ConstraintType.FORBIDDEN, ConstraintType.PRESERVE}
)
_SOFT_TYPES = frozenset({ConstraintType.PREFERRED, ConstraintType.OPTIONAL})
_CHANGE_ACTIONS = frozenset(
    {"ADD", "REMOVE", "REPLACE", "CHANGE", "MODIFY", "DELETE", "MOVE"}
)
_OUTPUT_CONDITION = re.compile(
    r"^if output type is ([a-z0-9_]+), (require|do not|preserve) (.+)$"
)
_PROJECT_CONDITION = re.compile(
    r'^if active project is "([^"]+)", (require|do not|preserve) (.+)$'
)


def _hard_type(constraint: Constraint) -> ConstraintType | None:
    if constraint.constraint_type in _HARD_TYPES:
        return constraint.constraint_type
    if (
        constraint.constraint_type is ConstraintType.CONDITIONAL
        and constraint.condition is not None
        and constraint.condition.evaluation is ConditionEvaluation.TRUE
    ):
        return constraint.underlying_constraint_type
    return None


def _is_soft(constraint: Constraint) -> bool:
    return constraint.constraint_type in _SOFT_TYPES


def _comparison_tuple(
    constraint: Constraint,
    evidence: ConstraintSourceEvidence,
) -> tuple[str, ...]:
    authority = "HARD" if _hard_type(constraint) is not None else (
        "SOFT" if _is_soft(constraint) else constraint.constraint_type.value
    )
    recency = (
        f"message:{evidence.source_message_sequence:020d}"
        if evidence.source_message_sequence is not None
        else f"time:{evidence.source_created_at.isoformat()}"
    )
    return (
        f"priority:{constraint.priority:04d}",
        f"authority:{authority}",
        recency,
        f"rule:{constraint.normalized_rule}",
        f"id:{constraint.id}",
    )


def _recency_compare(
    left: ConstraintSourceEvidence,
    right: ConstraintSourceEvidence,
) -> int:
    if (
        left.source_message_sequence is not None
        and right.source_message_sequence is not None
    ):
        return (left.source_message_sequence > right.source_message_sequence) - (
            left.source_message_sequence < right.source_message_sequence
        )
    return (left.source_created_at > right.source_created_at) - (
        left.source_created_at < right.source_created_at
    )


def _direct_key(target_key: str) -> tuple[str, str]:
    action, separator, object_atom = target_key.partition(":")
    if not separator:
        return target_key, ""
    return action, object_atom


def _opposes(
    left: Constraint,
    left_key: str,
    right: Constraint,
    right_key: str,
) -> bool:
    left_type = _hard_type(left)
    right_type = _hard_type(right)
    left_action, left_object = _direct_key(left_key)
    right_action, right_object = _direct_key(right_key)

    if left_type is not None and right_type is not None:
        if {left_type, right_type} == {
            ConstraintType.REQUIRED,
            ConstraintType.FORBIDDEN,
        }:
            return left_key == right_key
        if left_type is ConstraintType.PRESERVE:
            return (
                right_type is ConstraintType.REQUIRED
                and right_action in _CHANGE_ACTIONS
                and left_object == right_object
            )
        if right_type is ConstraintType.PRESERVE:
            return (
                left_type is ConstraintType.REQUIRED
                and left_action in _CHANGE_ACTIONS
                and left_object == right_object
            )
        return False

    if _is_soft(left) and right_type is not None:
        return (
            right_type is ConstraintType.FORBIDDEN and left_key == right_key
        ) or (
            right_type is ConstraintType.PRESERVE
            and left_action in _CHANGE_ACTIONS
            and right_object == left_object
        )
    if _is_soft(right) and left_type is not None:
        return _opposes(right, right_key, left, left_key)
    return _is_soft(left) and _is_soft(right) and left_key == right_key and (
        left.normalized_rule != right.normalized_rule
        or left.constraint_type is not right.constraint_type
    )


def _winner(
    left: Constraint,
    left_evidence: ConstraintSourceEvidence,
    right: Constraint,
    right_evidence: ConstraintSourceEvidence,
) -> int:
    """Return -1 for left, 1 for right, or 0 for an exact hard tie."""

    left_hard = _hard_type(left) is not None
    right_hard = _hard_type(right) is not None
    if left_hard != right_hard:
        return -1 if left_hard else 1
    if left.priority != right.priority:
        return -1 if left.priority > right.priority else 1
    recency = _recency_compare(left_evidence, right_evidence)
    if recency:
        return -1 if recency > 0 else 1
    if left_hard and right_hard:
        return 0
    left_order = (left.normalized_rule, str(left.id))
    right_order = (right.normalized_rule, str(right.id))
    return -1 if left_order < right_order else 1


def _conflict_id(target_key: str, constraints: tuple[Constraint, Constraint]) -> str:
    value = f"{target_key}|{'|'.join(sorted(str(item.id) for item in constraints))}"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"hard-conflict-{digest}"


def _predicate(
    constraint_type: ConstraintType,
    action: str,
    object_text: str,
) -> tuple[str, str]:
    action_atom = predicate_atom(action)
    object_atom = predicate_atom(object_text)
    target_key = f"{action_atom}:{object_atom}"
    if constraint_type is ConstraintType.REQUIRED:
        return f"MUST_{action_atom}:{object_atom}", target_key
    if constraint_type is ConstraintType.FORBIDDEN:
        return f"MUST_NOT_{action_atom}:{object_atom}", target_key
    if constraint_type is ConstraintType.PREFERRED:
        return f"PREFER_{action_atom}:{object_atom}", target_key
    if constraint_type is ConstraintType.OPTIONAL:
        return f"MAY_{action_atom}:{object_atom}", target_key
    if constraint_type is ConstraintType.ASSUMED:
        return f"ASSUME_{action_atom}:{object_atom}", target_key
    raise LifecycleInvariantError(f"Unsupported action predicate type: {constraint_type}.")


class DeterministicConstraintEngine:
    """Extract and resolve constraints without persistence or provider access."""

    def __init__(self, settings: ContextSettings, id_generator: IdGenerator) -> None:
        self._settings = settings
        self._ids = id_generator

    def _new_constraint(
        self,
        request: ConstraintEvaluationRequest,
        *,
        ordinal: int,
        constraint_type: ConstraintType,
        normalized_rule: str,
        target_key: str,
        source_kind: ConstraintSourceKind,
        source_text: str,
        priority: int,
        rule_ids: tuple[str, ...],
        matched_texts: tuple[str, ...],
        resolution_status: ConstraintResolutionStatus = ConstraintResolutionStatus.ACTIVE,
        underlying_type: ConstraintType | None = None,
        condition: Condition | None = None,
        has_source_message_sequence: bool = True,
    ) -> tuple[Constraint, ConstraintSourceEvidence]:
        constraint = Constraint(
            self._ids.new_id(),
            request.interpretation.interpretation.processing_run_id,
            request.message.id,
            ordinal,
            constraint_type,
            underlying_type,
            ConstraintScope.CURRENT_RESPONSE,
            normalized_rule,
            priority,
            source_kind,
            source_text,
            request.interpretation.interpretation.confidence,
            resolution_status,
            None,
            condition,
            request.evaluated_at,
        )
        evidence = ConstraintSourceEvidence(
            constraint.id,
            target_key,
            rule_ids,
            matched_texts,
            request.message.sequence_number if has_source_message_sequence else None,
            request.message.created_at if has_source_message_sequence else request.evaluated_at,
            ("pending",),
        )
        return constraint, evidence

    def _qualifier_constraints(
        self,
        request: ConstraintEvaluationRequest,
    ) -> list[tuple[Constraint, ConstraintSourceEvidence]]:
        results: list[tuple[Constraint, ConstraintSourceEvidence]] = []
        qualifiers = request.interpretation.interpretation.qualifiers
        has_only = any(item.kind is QualifierKind.ONLY for item in qualifiers)

        def append(
            *,
            qualifier: object,
            constraint_type: ConstraintType,
            normalized_rule: str,
            target_key: str,
        ) -> None:
            results.append(
                self._new_constraint(
                    request,
                    ordinal=len(results),
                    constraint_type=constraint_type,
                    normalized_rule=normalized_rule,
                    target_key=target_key,
                    source_kind=ConstraintSourceKind.CURRENT_MESSAGE,
                    source_text=request.message.original_text,
                    priority=PriorityBand.CURRENT_HARD.value,
                    rule_ids=(getattr(qualifier, "rule_id"),),
                    matched_texts=(getattr(qualifier, "matched_text"),),
                )
            )

        for qualifier in qualifiers:
            captures = qualifier.captures
            if "capture_error" in captures:
                continue
            if qualifier.kind is QualifierKind.ONLY:
                action = str(captures["action"])
                object_text = str(captures["object"])
                rule, target = _predicate(
                    ConstraintType.REQUIRED, action, object_text
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.REQUIRED,
                    normalized_rule=rule,
                    target_key=target,
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.PRESERVE,
                    normalized_rule="MUST_PRESERVE:UNSPECIFIED_CONTENT",
                    target_key="PRESERVE:UNSPECIFIED_CONTENT",
                )
            elif qualifier.kind is QualifierKind.EXACTLY:
                target = predicate_atom(str(captures["target"]))
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.REQUIRED,
                    normalized_rule=f"MUST_EXACTLY:{target}",
                    target_key=f"EXACTLY:{target}",
                )
            elif qualifier.kind is QualifierKind.APPROXIMATE:
                rule, target = _predicate(
                    ConstraintType.PREFERRED,
                    str(captures["action"]),
                    str(captures["object"]),
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.PREFERRED,
                    normalized_rule=rule,
                    target_key=target,
                )
            elif qualifier.kind is QualifierKind.PROHIBITION:
                object_text = str(captures["object"])
                if has_only and object_text == "anything else":
                    object_text = "unspecified content"
                rule, target = _predicate(
                    ConstraintType.FORBIDDEN,
                    str(captures["action"]),
                    object_text,
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.FORBIDDEN,
                    normalized_rule=rule,
                    target_key=target,
                )
            elif qualifier.kind is QualifierKind.PRESERVATION:
                object_atom = predicate_atom(str(captures["object"]))
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.PRESERVE,
                    normalized_rule=f"MUST_PRESERVE:{object_atom}",
                    target_key=f"PRESERVE:{object_atom}",
                )
            elif qualifier.kind is QualifierKind.SUBSTITUTION:
                action = str(captures["action"])
                forbidden, forbidden_target = _predicate(
                    ConstraintType.FORBIDDEN,
                    action,
                    str(captures["replaced"]),
                )
                required, required_target = _predicate(
                    ConstraintType.REQUIRED,
                    action,
                    str(captures["replacement"]),
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.FORBIDDEN,
                    normalized_rule=forbidden,
                    target_key=forbidden_target,
                )
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.REQUIRED,
                    normalized_rule=required,
                    target_key=required_target,
                )
            elif qualifier.kind is QualifierKind.SEQUENTIAL:
                append(
                    qualifier=qualifier,
                    constraint_type=ConstraintType.REQUIRED,
                    normalized_rule="MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME",
                    target_key="PRESENT:ONE_ORDERED_STEP_AT_A_TIME",
                )
        return results

    def _condition_constraint(
        self,
        request: ConstraintEvaluationRequest,
        ordinal: int,
    ) -> tuple[tuple[Constraint, ConstraintSourceEvidence] | None, bool]:
        normalized = normalize_phrase(request.message.original_text)
        if not normalized.startswith("if "):
            return None, False
        output_match = _OUTPUT_CONDITION.fullmatch(normalized)
        project_match = _PROJECT_CONDITION.fullmatch(normalized)
        if output_match is None and project_match is None:
            return None, True

        match = output_match or project_match
        assert match is not None
        expected_raw, clause_kind, clause = match.groups()
        if output_match is not None:
            try:
                expected_output = OutputType(expected_raw.upper())
            except ValueError:
                return None, True
            condition = Condition(
                CONDITION_GRAMMAR_VERSION,
                ConditionKind.OUTPUT_TYPE_EQUALS,
                expected_output.value,
                ConditionEvaluation.TRUE
                if request.interpretation.interpretation.expected_output_type
                is expected_output
                else ConditionEvaluation.FALSE,
            )
        else:
            expected_project = normalize_capture(expected_raw, remove_determiners=False)
            if not expected_project:
                return None, True
            active_project = (
                None
                if request.active_project_name is None
                else normalize_capture(
                    request.active_project_name,
                    remove_determiners=False,
                )
            )
            condition = Condition(
                CONDITION_GRAMMAR_VERSION,
                ConditionKind.ACTIVE_PROJECT_EQUALS,
                expected_project,
                ConditionEvaluation.TRUE
                if active_project == expected_project
                else ConditionEvaluation.FALSE,
            )

        try:
            if clause_kind == "preserve":
                object_atom = predicate_atom(clause)
                underlying = ConstraintType.PRESERVE
                rule = f"MUST_PRESERVE:{object_atom}"
                target = f"PRESERVE:{object_atom}"
            else:
                action, object_text = split_action_object(clause)
                underlying = (
                    ConstraintType.REQUIRED
                    if clause_kind == "require"
                    else ConstraintType.FORBIDDEN
                )
                rule, target = _predicate(underlying, action, object_text)
        except LifecycleInvariantError:
            return None, True

        result = self._new_constraint(
            request,
            ordinal=ordinal,
            constraint_type=ConstraintType.CONDITIONAL,
            normalized_rule=rule,
            target_key=target,
            source_kind=ConstraintSourceKind.CURRENT_MESSAGE,
            source_text=request.message.original_text,
            priority=PriorityBand.TRUE_CONDITIONAL.value,
            rule_ids=("condition.mvp-v1",),
            matched_texts=(request.message.original_text,),
            resolution_status=(
                ConstraintResolutionStatus.ACTIVE
                if condition.evaluation is ConditionEvaluation.TRUE
                else ConstraintResolutionStatus.INACTIVE
            ),
            underlying_type=underlying,
            condition=condition,
        )
        return result, False

    def evaluate(self, request: ConstraintEvaluationRequest) -> ConstraintDecision:
        interpretation = request.interpretation
        policy = ResponsePolicy(
            interpretation.interpretation.expected_output_type,
            interpretation.rule_set_version,
        )
        if interpretation.clarification_reason is not None:
            return ConstraintDecision(
                (),
                (),
                (),
                policy,
                interpretation.clarification_reason,
                interpretation.clarification_details,
            )

        generated: list[tuple[Constraint, ConstraintSourceEvidence]] = []
        normalized_message = normalize_phrase(request.message.original_text)
        if not normalized_message.startswith("if "):
            generated.extend(self._qualifier_constraints(request))

        conditional, unsupported_condition = self._condition_constraint(
            request, len(generated)
        )
        if conditional is not None:
            generated.append(conditional)

        policy_constraint = self._new_constraint(
            request,
            ordinal=len(generated),
            constraint_type=ConstraintType.FORBIDDEN,
            normalized_rule="MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
            target_key="EXECUTE:IMAGE_OR_ACTION",
            source_kind=ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
            source_text="MVP text-only/no-actions policy",
            priority=PriorityBand.CURRENT_HARD.value,
            rule_ids=("policy.text-only",),
            matched_texts=("text-only/no-actions",),
            has_source_message_sequence=False,
        )
        generated.append(policy_constraint)

        constraints = [item[0] for item in generated] + list(
            request.eligible_constraints
        )
        for constraint in constraints:
            require_priority_band(constraint.priority)
            if constraint.constraint_type is ConstraintType.ASSUMED and (
                constraint.source_kind is not ConstraintSourceKind.ASSUMPTION
                or constraint.priority != PriorityBand.ASSUMED.value
            ):
                raise LifecycleInvariantError(
                    "ASSUMED constraints require ASSUMPTION source and priority 0."
                )
        evidence = [item[1] for item in generated] + list(request.eligible_evidence)
        evidence_by_id = {item.constraint_id: item for item in evidence}
        evidence = [
            replace(
                item,
                comparison_tuple=_comparison_tuple(
                    next(
                        constraint
                        for constraint in constraints
                        if constraint.id == item.constraint_id
                    ),
                    item,
                ),
            )
            for item in evidence
        ]
        evidence_by_id = {item.constraint_id: item for item in evidence}

        if unsupported_condition:
            return ConstraintDecision(
                tuple(constraints),
                tuple(evidence),
                (),
                policy,
                ClarificationReason.UNSUPPORTED_CONDITION,
                FrozenJsonObject(
                    {
                        "source_message_id": str(request.message.id),
                        "condition_text": request.message.original_text,
                    }
                ),
            )

        conflict_groups: list[ConstraintConflictGroup] = []
        for left_index, left in enumerate(constraints):
            if left.resolution_status is not ConstraintResolutionStatus.ACTIVE:
                continue
            for right_index in range(left_index + 1, len(constraints)):
                right = constraints[right_index]
                if right.resolution_status is not ConstraintResolutionStatus.ACTIVE:
                    continue
                left_evidence = evidence_by_id[left.id]
                right_evidence = evidence_by_id[right.id]
                if not _opposes(
                    left,
                    left_evidence.target_key,
                    right,
                    right_evidence.target_key,
                ):
                    continue
                winner = _winner(left, left_evidence, right, right_evidence)
                if winner == 0:
                    group_id = _conflict_id(
                        left_evidence.target_key,
                        (left, right),
                    )
                    constraints[left_index] = replace(
                        left,
                        resolution_status=ConstraintResolutionStatus.CONFLICTING,
                        conflict_group_id=group_id,
                    )
                    constraints[right_index] = replace(
                        right,
                        resolution_status=ConstraintResolutionStatus.CONFLICTING,
                        conflict_group_id=group_id,
                    )
                    conflict_groups.append(
                        ConstraintConflictGroup(
                            group_id,
                            left_evidence.target_key,
                            tuple(sorted((left.id, right.id), key=str)),
                        )
                    )
                    break
                loser_index = right_index if winner == -1 else left_index
                constraints[loser_index] = replace(
                    constraints[loser_index],
                    resolution_status=ConstraintResolutionStatus.OVERRIDDEN,
                )
                if loser_index == left_index:
                    break

        material_assumptions: list[Constraint] = []
        for index, constraint in enumerate(constraints):
            if constraint.constraint_type is not ConstraintType.ASSUMED:
                continue
            evidence_item = evidence_by_id[constraint.id]
            entailed = any(
                candidate.id != constraint.id
                and candidate.constraint_type is not ConstraintType.ASSUMED
                and candidate.resolution_status is ConstraintResolutionStatus.ACTIVE
                and evidence_by_id[candidate.id].target_key == evidence_item.target_key
                and (
                    _hard_type(candidate) is ConstraintType.REQUIRED
                    or _is_soft(candidate)
                    or (
                        _hard_type(candidate) is ConstraintType.PRESERVE
                        and evidence_item.target_key.startswith("PRESERVE:")
                    )
                )
                for candidate in constraints
            )
            if entailed:
                constraints[index] = replace(
                    constraint,
                    resolution_status=ConstraintResolutionStatus.OVERRIDDEN,
                )
            else:
                material_assumptions.append(constraint)

        clarification_reason: ClarificationReason | None = None
        details: FrozenJsonObject | None = None
        if conflict_groups:
            clarification_reason = ClarificationReason.HARD_CONSTRAINT_CONFLICT
            group_ids = set(conflict_groups[0].constraint_ids)
            rules = sorted(
                constraint.normalized_rule
                for constraint in constraints
                if constraint.id in group_ids
            )
            details = FrozenJsonObject(
                {
                    "conflict_group_id": conflict_groups[0].id,
                    "rule_a": rules[0],
                    "rule_b": rules[1],
                }
            )
        elif material_assumptions:
            clarification_reason = ClarificationReason.MATERIAL_ASSUMPTION
            assumption = min(
                material_assumptions,
                key=lambda item: (item.ordinal, str(item.id)),
            )
            details = FrozenJsonObject(
                {
                    "constraint_id": str(assumption.id),
                    "assumed_rule": assumption.normalized_rule,
                }
            )

        return ConstraintDecision(
            tuple(constraints),
            tuple(evidence),
            tuple(conflict_groups),
            policy,
            clarification_reason,
            details,
        )


__all__ = ["DeterministicConstraintEngine"]
