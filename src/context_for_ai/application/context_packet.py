"""Atomic application stage for deterministic context-packet construction."""

from __future__ import annotations

from dataclasses import replace

from context_for_ai.domain.enums import (
    ContextBudgetPhase,
    FailureCode,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import SafeFailure
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    ContextPacketBuilder,
    ContextPacketBuildRequest,
    ContextPacketBuildResult,
    ContextPacketBuildSuccess,
)
from context_for_ai.domain.ports.repositories import (
    ContextPacketRepository,
    ModelCallRepository,
    ProcessingRunRepository,
)
from context_for_ai.domain.ports.system import IdGenerator, TransactionBoundary
from context_for_ai.domain.value_objects import FrozenJsonObject


_BUDGET_FAILURE_MESSAGE = (
    "The required context exceeds the configured prompt budget."
)


class ContextPacketStageService:
    """Build and atomically persist exactly one initial context outcome."""

    def __init__(
        self,
        *,
        builder: ContextPacketBuilder,
        packets: ContextPacketRepository,
        runs: ProcessingRunRepository,
        model_calls: ModelCallRepository,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._builder = builder
        self._packets = packets
        self._runs = runs
        self._model_calls = model_calls
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(
        self,
        request: ContextPacketBuildRequest,
    ) -> ContextPacketBuildResult:
        run = request.processing_run
        if run.status is not ProcessingRunStatus.PERSISTED:
            raise LifecycleInvariantError(
                "Context packet stage requires a PERSISTED processing run."
            )

        result = self._builder.build(request)
        if isinstance(result, ContextPacketBuildSuccess):
            packet = result.record.packet
            if (
                packet.id != request.context_packet_id
                or packet.processing_run_id != run.id
                or packet.message_id != request.message.id
            ):
                raise LifecycleInvariantError(
                    "Context packet builder result must belong to the stage request."
                )
            context_ready = replace(run, status=ProcessingRunStatus.CONTEXT_READY)
            with self._transactions.transaction():
                self._packets.add(result.record)
                self._runs.update(context_ready)
            return result

        if not isinstance(result, ContextBudgetExceeded):
            raise LifecycleInvariantError(
                "Context packet builder returned an unknown result type."
            )
        if result.context_packet_id != request.context_packet_id:
            raise LifecycleInvariantError(
                "Context packet builder result must match the preallocated packet ID."
            )
        if result.phase is not ContextBudgetPhase.INITIAL:
            raise LifecycleInvariantError(
                "Context packet stage accepts only initial budget overflow."
            )

        failure = SafeFailure(
            id=self._id_generator.new_id(),
            processing_run_id=run.id,
            stage=PipelineStage.CONTEXT,
            error_code=FailureCode.CONTEXT_BUDGET_EXCEEDED,
            safe_message=_BUDGET_FAILURE_MESSAGE,
            details=FrozenJsonObject(
                {
                    "token_estimator": result.token_estimator,
                    "estimated_required_tokens": result.estimated_required_tokens,
                    "effective_prompt_budget": result.effective_prompt_budget,
                }
            ),
            is_terminal=True,
            created_at=request.created_at,
        )
        controlled_failure = replace(
            run,
            status=ProcessingRunStatus.CONTROLLED_FAILURE,
            completed_at=request.created_at,
        )
        with self._transactions.transaction():
            self._model_calls.add_failure(failure)
            self._runs.update(controlled_failure)
        return result


__all__ = ["ContextPacketStageService"]
