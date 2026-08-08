"""Pure deterministic construction of immutable context-packet-v2 aggregates."""

from __future__ import annotations

from decimal import Decimal

from context_for_ai.context_engine.prompt_rendering import (
    DeterministicPromptRenderer,
    _plan_initial,
    effective_prompt_budget,
)
from context_for_ai.context_engine.retrieval import normalize_retrieval_content
from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    PROMPT_POLICY_VERSION,
    TOKEN_ESTIMATOR_VERSION,
    Condition,
    Constraint,
    ConstraintPacketLineage,
    ConstraintSourceEvidence,
    ContextPacket,
    ReferenceCandidateEvidence,
)
from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    MemoryStatus,
    OutputType,
    ReferenceStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import overall_confidence
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    ContextPacketBuildRequest,
    ContextPacketBuildResult,
    ContextPacketBuildSuccess,
    PromptRenderRequest,
    PromptRenderResult,
)
from context_for_ai.domain.ports.records import ContextPacketRecord
from context_for_ai.domain.value_objects import (
    FrozenJsonObject,
    UnitScore,
    format_utc_timestamp,
)


_MODEL_OUTPUT_TYPES = frozenset(
    {
        OutputType.TEXT_ANSWER,
        OutputType.TEXT_EXPLANATION,
        OutputType.TEXT_DESCRIPTION,
        OutputType.TEXT_PLAN,
        OutputType.TEXT_ANALYSIS,
        OutputType.TEXT_CODE,
        OutputType.TEXT_COMPARISON,
    }
)
_CANONICAL_REFERENCE_SCORES = {
    Decimal("0"): Decimal("0"),
    Decimal("0.6"): Decimal("0.6"),
    Decimal("0.8"): Decimal("0.8"),
    Decimal("0.9"): Decimal("0.9"),
    Decimal("1"): Decimal("1"),
}
_MEMORY_SOURCE_KINDS = frozenset(
    {
        ConstraintSourceKind.CORRECTION_MEMORY,
        ConstraintSourceKind.PREFERENCE_MEMORY,
        ConstraintSourceKind.RETRIEVED_MEMORY,
    }
)


def _candidate_json(value: ReferenceCandidateEvidence) -> FrozenJsonObject:
    try:
        score = _CANONICAL_REFERENCE_SCORES[value.score.value]
    except KeyError as error:
        raise LifecycleInvariantError(
            "Reference candidate score is outside the canonical packet projection."
        ) from error
    return FrozenJsonObject(
        {
            "rank": value.rank,
            "entity_id": None if value.entity_id is None else str(value.entity_id),
            "entity_type": None if value.entity_type is None else value.entity_type.value,
            "display_name": value.display_name,
            "normalized_name": value.normalized_name,
            "score": score,
            "rank_reason": value.rank_reason.value,
            "entity_source_message_id": (
                None
                if value.entity_source_message_id is None
                else str(value.entity_source_message_id)
            ),
            "evidence_message_id": (
                None if value.evidence_message_id is None else str(value.evidence_message_id)
            ),
            "evidence_message_sequence": value.evidence_message_sequence,
            "prior_mention_ordinal": value.prior_mention_ordinal,
            "is_active": value.is_active,
        }
    )


def _condition_json(value: Condition | None) -> FrozenJsonObject | None:
    if value is None:
        return None
    return FrozenJsonObject(
        {
            "grammar_version": value.grammar_version,
            "kind": value.kind.value,
            "expected_value": value.expected_value,
            "evaluation": value.evaluation.value,
        }
    )


def _validate_constraint_lineage(
    request: ContextPacketBuildRequest,
    constraint: Constraint,
    lineage: ConstraintPacketLineage,
    constraint_ids: frozenset[object],
) -> None:
    if any(value not in constraint_ids for value in lineage.related_constraint_ids):
        raise LifecycleInvariantError(
            "Constraint packet lineage may reference only decision constraints."
        )
    if constraint.resolution_status is ConstraintResolutionStatus.OVERRIDDEN:
        if lineage.winner_constraint_id is None:
            raise LifecycleInvariantError(
                "Overridden constraint requires winner packet lineage."
            )
    elif lineage.winner_constraint_id is not None:
        raise LifecycleInvariantError(
            "Only an overridden constraint may have winner packet lineage."
        )

    if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE:
        if (
            lineage.source_message_id != request.message.id
            or lineage.source_memory_id is not None
            or lineage.source_state is not None
        ):
            raise LifecycleInvariantError(
                "CURRENT_MESSAGE constraint lineage must name only the current message."
            )
    elif constraint.source_kind in _MEMORY_SOURCE_KINDS:
        if lineage.source_memory_id is None or lineage.source_state is not None:
            raise LifecycleInvariantError(
                "Memory constraint lineage must name its originating memory."
            )
    if lineage.source_state is not None and (
        lineage.source_state.conversation_id != request.state.conversation_id
        or lineage.source_state.version != request.state.version
    ):
        raise LifecycleInvariantError(
            "Constraint state lineage must name the represented state snapshot."
        )


def _constraint_json(
    request: ContextPacketBuildRequest,
    constraint: Constraint,
    evidence: ConstraintSourceEvidence,
    lineage: ConstraintPacketLineage,
    constraint_ids: frozenset[object],
) -> FrozenJsonObject:
    _validate_constraint_lineage(request, constraint, lineage, constraint_ids)
    source_state = (
        None if lineage.source_state is None else lineage.source_state.to_json_object()
    )
    source_evidence = FrozenJsonObject(
        {
            "constraint_id": str(constraint.id),
            "target_key": evidence.target_key,
            "contributing_rule_ids": evidence.contributing_rule_ids,
            "source_texts": evidence.source_texts,
            "source_message_id": (
                None if lineage.source_message_id is None else str(lineage.source_message_id)
            ),
            "source_memory_id": (
                None if lineage.source_memory_id is None else str(lineage.source_memory_id)
            ),
            "source_state": source_state,
            "source_message_sequence": evidence.source_message_sequence,
            "source_created_at": format_utc_timestamp(evidence.source_created_at),
            "comparison_tuple": evidence.comparison_tuple,
            "winner_constraint_id": (
                None
                if lineage.winner_constraint_id is None
                else str(lineage.winner_constraint_id)
            ),
            "related_constraint_ids": tuple(
                str(value) for value in lineage.related_constraint_ids
            ),
        }
    )
    return FrozenJsonObject(
        {
            "ordinal": constraint.ordinal,
            "id": str(constraint.id),
            "type": constraint.constraint_type.value,
            "underlying_type": (
                None
                if constraint.underlying_constraint_type is None
                else constraint.underlying_constraint_type.value
            ),
            "scope": constraint.scope.value,
            "normalized_rule": constraint.normalized_rule,
            "priority": constraint.priority,
            "source_kind": constraint.source_kind.value,
            "source_evidence": source_evidence,
            "confidence": constraint.confidence.value,
            "status": constraint.resolution_status.value,
            "conflict_group_id": constraint.conflict_group_id,
            "condition": _condition_json(constraint.condition),
        }
    )


def _topic_terms(label: str) -> tuple[str, ...]:
    tokens = normalize_retrieval_content(label).split()
    return tuple(dict.fromkeys(tokens))


class DeterministicContextPacketBuilder:
    """Build a complete packet-v2 projection from explicit immutable decisions."""

    def build(self, request: ContextPacketBuildRequest) -> ContextPacketBuildResult:
        interpretation = request.interpretation.interpretation
        if (
            interpretation.intent is IntentType.UNSUPPORTED
            or interpretation.expected_output_type not in _MODEL_OUTPUT_TYPES
        ):
            raise LifecycleInvariantError(
                "Unsupported or application-produced output cannot reach packet construction."
            )
        if (
            request.constraint_decision.response_policy.expected_output_type
            is not interpretation.expected_output_type
            or request.constraint_decision.response_policy.text_only is not True
            or request.constraint_decision.response_policy.actions_allowed is not False
        ):
            raise LifecycleInvariantError(
                "Constraint response policy must equal the interpreted text-only output."
            )

        constraints = request.constraint_decision.constraints
        if len({value.id for value in constraints}) != len(constraints) or len(
            {value.ordinal for value in constraints}
        ) != len(constraints):
            raise LifecycleInvariantError("Packet constraints require unique IDs and ordinals.")
        if request.constraint_decision.conflict_groups or any(
            value.resolution_status is ConstraintResolutionStatus.CONFLICTING
            or (
                value.constraint_type is ConstraintType.ASSUMED
                and value.resolution_status is ConstraintResolutionStatus.ACTIVE
            )
            or (
                value.condition is not None
                and value.condition.evaluation is ConditionEvaluation.UNSUPPORTED
            )
            for value in constraints
        ):
            raise LifecycleInvariantError(
                "Conflicting, unsupported, or active assumed constraints cannot be packetized."
            )

        validation = request.validation_configuration
        shape_rule = next(
            (
                value
                for value in validation.output_shape_rules
                if value.output_type is interpretation.expected_output_type
            ),
            None,
        )
        if shape_rule is None:
            raise LifecycleInvariantError("No validation output-shape rule matches the request.")

        references = tuple(
            FrozenJsonObject(
                {
                    "id": str(value.id),
                    "mention_ordinal": value.mention_ordinal,
                    "surface_text": value.surface_text,
                    "status": value.status.value,
                    "entity_id": (
                        None
                        if value.resolved_entity_id is None
                        else str(value.resolved_entity_id)
                    ),
                    "source_message_id": (
                        None if value.source_message_id is None else str(value.source_message_id)
                    ),
                    "confidence": value.confidence.value,
                    "evidence": tuple(_candidate_json(item) for item in value.candidate_evidence),
                }
            )
            for value in request.reference_outcomes
        )

        evidence_by_id = {
            value.constraint_id: value for value in request.constraint_decision.evidence
        }
        lineage_by_id = {
            value.constraint_id: value for value in request.constraint_packet_lineage
        }
        constraint_ids = frozenset(value.id for value in constraints)
        packet_constraints = tuple(
            _constraint_json(
                request,
                value,
                evidence_by_id[value.id],
                lineage_by_id[value.id],
                constraint_ids,
            )
            for value in constraints
        )

        selected = tuple(zip(request.retrieval_decision.selected, request.selected_memories, strict=True))
        if any(memory.status is not MemoryStatus.ACTIVE for _, memory in selected):
            raise LifecycleInvariantError("Selected packet memories must be active snapshots.")
        retrieval = tuple(
            FrozenJsonObject(
                {
                    "memory_id": str(memory.id),
                    "content": memory.content,
                    "score": result.score.value,
                    "rank": result.rank,
                    "reasons": result.reasons,
                    "scope": memory.scope.value,
                    "confidence": memory.confidence.value,
                }
            )
            for result, memory in selected
        )

        material_reference_scores = tuple(
            value.confidence
            for value in request.reference_outcomes
            if value.status is ReferenceStatus.RESOLVED
        )
        reference_confidence = (
            None if not material_reference_scores else min(material_reference_scores)
        )
        retrieval_confidence = request.retrieval_decision.confidence
        confidence = FrozenJsonObject(
            {
                "interpretation": interpretation.confidence.value,
                "references": (
                    None
                    if reference_confidence is None
                    else reference_confidence.value
                ),
                "retrieval": (
                    None
                    if retrieval_confidence is None
                    else retrieval_confidence.value
                ),
                "overall": overall_confidence(
                    interpretation=interpretation.confidence,
                    reference_resolution=reference_confidence,
                    retrieval=retrieval_confidence,
                ).value,
            }
        )

        active_topic = (
            None
            if request.active_topic is None
            else FrozenJsonObject(
                {
                    "topic_id": str(request.active_topic.id),
                    "terms": _topic_terms(request.active_topic.label),
                }
            )
        )
        response_policy = FrozenJsonObject(
            {
                "output_type": interpretation.expected_output_type.value,
                "validate_before_display": True,
                "text_only": True,
                "no_actions": True,
                "streaming": False,
                "correction_limit": validation.max_revisions,
                "model_generation_limit": 1 + validation.max_revisions,
                "absolute_model_generation_cap": 3,
            }
        )
        payload_values: dict[str, object] = {
            "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
            "trace": {
                "processing_run_id": str(request.processing_run.id),
                "conversation_id": str(request.processing_run.conversation_id),
                "user_message_id": str(request.message.id),
                "state_version": request.state.version,
                "configuration_fingerprint": request.processing_run.configuration_fingerprint,
            },
            "request": {
                "original_text": request.message.original_text,
                "intent": interpretation.intent.value,
                "intent_rule_id": interpretation.intent_rule_id,
                "expected_output_type": interpretation.expected_output_type.value,
                "qualifiers": tuple(
                    FrozenJsonObject(
                        {
                            "kind": value.kind.value,
                            "rule_id": value.rule_id,
                            "matched_text": value.matched_text,
                        }
                    )
                    for value in interpretation.qualifiers
                ),
                "confidence": interpretation.confidence.value,
            },
            "active_state": {
                "project_id": (
                    None
                    if request.active_project_id is None
                    else str(request.active_project_id)
                ),
                "topic_id": (
                    None if request.state.active_topic_id is None else str(request.state.active_topic_id)
                ),
                "task_id": (
                    None if request.state.active_task_id is None else str(request.state.active_task_id)
                ),
                "previous_task_id": (
                    None
                    if request.state.previous_task_id is None
                    else str(request.state.previous_task_id)
                ),
                "topic_stack": tuple(str(value) for value in request.state.topic_stack),
            },
            "validation_context": {
                "rule_set_version": validation.rule_set_version,
                "active_topic": active_topic,
                "output_shape_rule": {
                    "id": shape_rule.id,
                    "output_type": shape_rule.output_type.value,
                    "shape": shape_rule.shape,
                },
                "preserve_change_verb_list_id": validation.preserve_change_verb_list_id,
                "preserve_change_verbs": validation.preserve_change_verbs,
                "action_markers": validation.action_markers,
            },
            "references": references,
            "constraints": packet_constraints,
            "retrieval": retrieval,
            "confidence": confidence,
            "response_policy": response_policy,
            "rendering": {
                "prompt_policy_version": PROMPT_POLICY_VERSION,
                "token_estimator": TOKEN_ESTIMATOR_VERSION,
                "token_budget": 0,
                "mandatory_estimated_tokens": 0,
                "estimated_prompt_tokens": 0,
                "included_sections": (),
                "omitted_sections": (),
            },
        }
        provisional = FrozenJsonObject(payload_values)
        budget = effective_prompt_budget(
            context_window_tokens=request.context_window_tokens,
            maximum_prompt_tokens=request.maximum_prompt_tokens,
            reserved_response_tokens=request.reserved_response_tokens,
        )
        plan = _plan_initial(
            context_packet_id=request.context_packet_id,
            packet_json=provisional,
            effective_budget=budget,
        )
        if isinstance(plan, ContextBudgetExceeded):
            return plan

        payload_values["rendering"] = plan.metadata.to_json_object()
        packet = ContextPacket(
            request.context_packet_id,
            request.processing_run.id,
            request.message.id,
            FrozenJsonObject(payload_values),
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            request.processing_run.configuration_fingerprint,
            request.created_at,
        )
        record = ContextPacketRecord(
            packet,
            request.retrieval_decision.selected,
            request.retrieval_decision.excluded,
        )
        initial_render = DeterministicPromptRenderer().render(
            PromptRenderRequest(packet, None)
        )
        if not isinstance(initial_render, PromptRenderResult):
            raise LifecycleInvariantError("A completed packet requires an initial prompt.")
        return ContextPacketBuildSuccess(record, initial_render)
