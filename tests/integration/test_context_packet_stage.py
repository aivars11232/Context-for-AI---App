"""SQLite integration coverage for the atomic TASK-0010 packet stage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from context_for_ai.application import ContextPacketStageService
from context_for_ai.context_engine import DeterministicContextPacketBuilder
from context_for_ai.domain.decisions import (
    ConstraintDecision,
    InterpretationDecision,
    RequestInterpretation,
    ResponsePolicy,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Message
from context_for_ai.domain.enums import (
    ContextBudgetPhase,
    FailureCode,
    IntentType,
    MessageRole,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.configuration import (
    OutputShapeRule,
    ValidationConfigurationSnapshot,
)
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    ContextPacketBuildRequest,
    ContextPacketBuildSuccess,
    RetrievalDecision,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.database import (
    SQLiteContextPacketRepository,
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteMessageRepository,
    SQLiteModelCallRepository,
    SQLiteProcessingRunRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
FINGERPRINT = "task-0010-stage-fingerprint"


def identifier(number: int) -> DomainId:
    return DomainId(f"70000000-0000-4000-8000-{number:012d}")


@dataclass(slots=True)
class CountingIds:
    value: DomainId
    calls: int = 0

    def new_id(self) -> DomainId:
        self.calls += 1
        return self.value


class FailingRunRepository:
    def update(self, run: ProcessingRun) -> None:
        raise PersistenceError("Induced processing-run write failure.")


class ForbiddenBuilder:
    def build(self, request: ContextPacketBuildRequest) -> object:
        raise AssertionError("The builder must not run for a non-PERSISTED request.")


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    path = apply_migrations(tmp_path / "context-packet-stage.sqlite3")
    opened = connect_database(path)
    yield opened
    opened.close()


def validation_configuration() -> ValidationConfigurationSnapshot:
    model_outputs = tuple(
        value
        for value in OutputType
        if value not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
    )
    return ValidationConfigurationSnapshot(
        FINGERPRINT,
        2,
        "validation-v1",
        tuple(
            OutputShapeRule(
                f"shape-{output.value.casefold()}",
                output,
                "NON_EMPTY_TEXT",
            )
            for output in model_outputs
        ),
        "preserve-v1",
        ("change", "remove"),
        ("TOOL_CALL:", "ACTION_EXECUTED:"),
    )


def seed_request(
    connection: sqlite3.Connection,
    *,
    maximum_prompt_tokens: int = 10_000,
) -> ContextPacketBuildRequest:
    transactions = SQLiteTransactionBoundary(connection)
    conversations = SQLiteConversationRepository(connection)
    states = SQLiteConversationStateRepository(connection)
    messages = SQLiteMessageRepository(connection)
    runs = SQLiteProcessingRunRepository(connection)

    conversation = Conversation(identifier(1), None, "Packet stage", NOW, NOW)
    state = ConversationState(
        conversation.id,
        None,
        None,
        None,
        OutputType.TEXT_EXPLANATION,
        (),
        0,
        NOW,
    )
    message = Message(
        identifier(2),
        conversation.id,
        MessageRole.USER,
        "Explain the immutable context packet.",
        NOW,
        0,
    )
    run = ProcessingRun(
        identifier(3),
        conversation.id,
        message.id,
        str(identifier(4)),
        ProcessingRunStatus.PERSISTED,
        state.version,
        FINGERPRINT,
        NOW,
        None,
    )
    with transactions.transaction():
        conversations.add(conversation)
        states.add(state)
        messages.add(message)
        runs.add(run)

    interpretation = InterpretationDecision(
        RequestInterpretation(
            run.id,
            message.id,
            IntentType.EXPLAIN,
            OutputType.TEXT_EXPLANATION,
            "intent-explain",
            (),
            UnitScore("0.9"),
            "Matched the explain rule.",
            NOW,
        ),
        "context-rules-v1",
        (),
        None,
        None,
        (),
        None,
        None,
    )
    constraints = ConstraintDecision(
        (),
        (),
        (),
        ResponsePolicy(OutputType.TEXT_EXPLANATION, "context-rules-v1"),
        None,
        None,
    )
    return ContextPacketBuildRequest(
        identifier(10),
        run,
        message,
        state,
        None,
        None,
        interpretation,
        (),
        constraints,
        (),
        RetrievalDecision((), (), None),
        (),
        16_384,
        maximum_prompt_tokens,
        512,
        validation_configuration(),
        NOW,
    )


def stage(
    connection: sqlite3.Connection,
    ids: CountingIds,
    *,
    runs: object | None = None,
    builder: object | None = None,
) -> ContextPacketStageService:
    return ContextPacketStageService(
        builder=builder or DeterministicContextPacketBuilder(),  # type: ignore[arg-type]
        packets=SQLiteContextPacketRepository(connection),
        runs=runs or SQLiteProcessingRunRepository(connection),  # type: ignore[arg-type]
        model_calls=SQLiteModelCallRepository(connection),
        id_generator=ids,
        transactions=SQLiteTransactionBoundary(connection),
    )


def test_success_atomically_persists_packet_and_context_ready_run(
    connection: sqlite3.Connection,
) -> None:
    request = seed_request(connection)
    ids = CountingIds(identifier(90))

    result = stage(connection, ids).execute(request)

    assert isinstance(result, ContextPacketBuildSuccess)
    assert ids.calls == 0
    assert SQLiteContextPacketRepository(connection).get(request.context_packet_id) == result.record
    stored_run = SQLiteProcessingRunRepository(connection).get(request.processing_run.id)
    assert stored_run == replace(
        request.processing_run,
        status=ProcessingRunStatus.CONTEXT_READY,
    )
    assert connection.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0] == 0


def test_initial_overflow_persists_only_exact_failure_and_terminal_run(
    connection: sqlite3.Connection,
) -> None:
    request = seed_request(connection, maximum_prompt_tokens=1)
    failure_id = identifier(91)
    ids = CountingIds(failure_id)

    result = stage(connection, ids).execute(request)

    assert isinstance(result, ContextBudgetExceeded)
    assert result.phase is ContextBudgetPhase.INITIAL
    assert ids.calls == 1
    assert SQLiteContextPacketRepository(connection).get_for_run(request.processing_run.id) is None
    failures = SQLiteModelCallRepository(connection).list_failures_for_run(
        request.processing_run.id
    )
    assert len(failures) == 1
    failure = failures[0]
    assert failure.id == failure_id
    assert failure.processing_run_id == request.processing_run.id
    assert failure.stage is PipelineStage.CONTEXT
    assert failure.error_code is FailureCode.CONTEXT_BUDGET_EXCEEDED
    assert failure.safe_message == (
        "The required context exceeds the configured prompt budget."
    )
    assert failure.details == FrozenJsonObject(
        {
            "token_estimator": result.token_estimator,
            "estimated_required_tokens": result.estimated_required_tokens,
            "effective_prompt_budget": result.effective_prompt_budget,
        }
    )
    assert failure.is_terminal is True
    assert failure.created_at == request.created_at
    assert SQLiteProcessingRunRepository(connection).get(request.processing_run.id) == replace(
        request.processing_run,
        status=ProcessingRunStatus.CONTROLLED_FAILURE,
        completed_at=request.created_at,
    )
    for table in (
        "context_packets",
        "retrieval_results",
        "retrieval_exclusions",
        "model_requests",
        "model_responses",
        "validation_results",
        "correction_attempts",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


@pytest.mark.parametrize("maximum_prompt_tokens", [10_000, 1])
def test_induced_run_write_failure_rolls_back_the_complete_stage_outcome(
    connection: sqlite3.Connection,
    maximum_prompt_tokens: int,
) -> None:
    request = seed_request(
        connection,
        maximum_prompt_tokens=maximum_prompt_tokens,
    )
    ids = CountingIds(identifier(92))

    with pytest.raises(PersistenceError, match="Induced"):
        stage(connection, ids, runs=FailingRunRepository()).execute(request)

    assert SQLiteContextPacketRepository(connection).get_for_run(request.processing_run.id) is None
    assert (
        SQLiteModelCallRepository(connection).list_failures_for_run(
            request.processing_run.id
        )
        == ()
    )
    assert SQLiteProcessingRunRepository(connection).get(request.processing_run.id) == (
        request.processing_run
    )
    assert ids.calls == (1 if maximum_prompt_tokens == 1 else 0)


def test_stage_joins_an_outer_transaction_and_outer_failure_rolls_back(
    connection: sqlite3.Connection,
) -> None:
    request = seed_request(connection)
    transactions = SQLiteTransactionBoundary(connection)

    with pytest.raises(RuntimeError, match="outer failure"):
        with transactions.transaction():
            result = stage(connection, CountingIds(identifier(93))).execute(request)
            assert isinstance(result, ContextPacketBuildSuccess)
            assert connection.in_transaction is True
            raise RuntimeError("outer failure")

    assert SQLiteContextPacketRepository(connection).get_for_run(request.processing_run.id) is None
    assert SQLiteProcessingRunRepository(connection).get(request.processing_run.id) == (
        request.processing_run
    )


def test_non_persisted_request_is_rejected_before_builder_or_writes(
    connection: sqlite3.Connection,
) -> None:
    request = seed_request(connection)
    invalid = replace(
        request,
        processing_run=replace(
            request.processing_run,
            status=ProcessingRunStatus.CONTEXT_READY,
        ),
    )

    with pytest.raises(LifecycleInvariantError, match="requires a PERSISTED"):
        stage(
            connection,
            CountingIds(identifier(94)),
            builder=ForbiddenBuilder(),
        ).execute(invalid)

    assert SQLiteContextPacketRepository(connection).get_for_run(request.processing_run.id) is None
    assert SQLiteProcessingRunRepository(connection).get(request.processing_run.id) == (
        request.processing_run
    )
