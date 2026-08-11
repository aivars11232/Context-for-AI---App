"""AT-016 opt-in, full-pipeline local Ollama smoke acceptance."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    CancelledResult,
    ConfigurationFailureResult,
    ControlledFailureResult,
    PersistenceFailureResult,
    ShellReadyResult,
    SucceededResult,
    ValidationExhaustedResult,
)
from context_for_ai.bootstrap import ProductionShellScopeFactory
from context_for_ai.context_engine import (
    DeterministicConstraintEngine,
    DeterministicContextRetriever,
    DeterministicInterpretationEngine,
)
from context_for_ai.context_engine.prompt_rendering import (
    conservative_utf8_estimate,
)
from context_for_ai.domain.entities import ConversationState, Message
from context_for_ai.domain.enums import (
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    MessageRole,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.ports import (
    CompletedGeneration,
    GenerationOutcome,
    GenerationRequest,
)
from context_for_ai.domain.ports.context import (
    ConstraintEvaluationRequest,
    InterpretationRequest,
    RetrievalRequest,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.configuration import (
    ApplicationConfiguration,
    ConfigurationError,
    load_configuration,
)
from context_for_ai.infrastructure.database import SQLiteValidationRepository
from context_for_ai.main import (
    StartupError,
    bootstrap_application,
    create_qml_engine,
    prepare_application_shell,
)
from context_for_ai.ui import ShellFacade
from tests.fixtures.at_016_acceptance import (
    SMOKE_SENTINEL,
    At016EvidenceWriteError,
    At016Failure,
    At016ModelEvidence,
    At016Prerequisites,
    At016ProviderEvidence,
    evaluate_at_016_gate,
    finalize_evidence,
    model_evidence,
    project_transport_failure,
    provider_evidence,
    retain_first_failure,
    validated_prerequisites,
    write_evidence,
)
from tests.fixtures.ollama_live import OllamaLiveOptIn


pytestmark = pytest.mark.ollama

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "at_016_local_ollama_smoke"
EVIDENCE_DIRECTORY = REPOSITORY_ROOT / "data" / "acceptance" / "at-016"
USER_MESSAGE = "Exactly answer CONTEXT_FOR_AI_SMOKE_OK."
EXPECTED_TRACE_NAMES = (
    "run_accepted",
    "context_built",
    "reference_resolved",
    "constraints_resolved",
    "retrieval_completed",
    "packet_built",
    "model_request_started",
    "model_request_finished",
    "validation_completed",
    "run_succeeded",
)
EXPECTED_TRACE_STAGES = (
    "ACCEPTANCE",
    "CONTEXT",
    "CONTEXT",
    "CONTEXT",
    "CONTEXT",
    "CONTEXT",
    "REQUEST",
    "TRANSPORT",
    "VALIDATION",
    "TERMINALIZATION",
)
TRACE_KEYS = frozenset(
    {
        "timestamp",
        "level",
        "event_name",
        "stage",
        "configuration_fingerprint",
        "conversation_id",
        "user_message_id",
        "processing_run_id",
        "context_packet_id",
        "model_request_id",
        "model_response_id",
        "validation_result_id",
        "clarification_request_id",
        "memory_id",
        "memory_revision_id",
        "correction_attempt_number",
        "error_type",
    }
)

LINEAGE_FAILURE = At016Failure("LINEAGE", "LINEAGE_MISMATCH")
PERSISTENCE_FAILURE = At016Failure("PERSISTENCE", "PERSISTENCE_ERROR")
TRACE_FAILURE = At016Failure("TRACE", "TRACE_ASSERTION_FAILED")
REDACTION_FAILURE = At016Failure("REDACTION", "REDACTION_ASSERTION_FAILED")
UI_FAILURE = At016Failure("UI", "UI_ASSERTION_FAILED")
UNEXPECTED_FAILURE = At016Failure("ACCEPTANCE", "UNEXPECTED_RESULT")


class _LiveCheckFailure(RuntimeError):
    def __init__(self, failure: At016Failure) -> None:
        self.failure = failure
        super().__init__(failure.code)


def _require(condition: object, failure: At016Failure = LINEAGE_FAILURE) -> None:
    if not condition:
        raise _LiveCheckFailure(failure) from None


@dataclass(slots=True)
class _Recorder:
    results: list[object] = field(default_factory=list)
    requests: list[GenerationRequest] = field(default_factory=list)
    outcomes: list[GenerationOutcome] = field(default_factory=list)
    first_failure: At016Failure | None = None
    result_ready: threading.Event = field(default_factory=threading.Event)

    def fail(self, failure: At016Failure) -> None:
        self.first_failure = retain_first_failure(self.first_failure, failure)


class _FixedIds:
    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> DomainId:
        value = DomainId(f"68000000-0000-4000-8000-{self._next:012x}")
        self._next += 1
        return value


class _ObservedGateway:
    """Observe the committed pre-provider state, then delegate once to Ollama."""

    def __init__(
        self,
        delegate: Any,
        recorder: _Recorder,
        preflight: Any,
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder
        self._preflight = preflight

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: Any,
    ) -> GenerationOutcome:
        self._recorder.requests.append(request)
        try:
            self._preflight(request)
        except _LiveCheckFailure:
            self._recorder.fail(UNEXPECTED_FAILURE)
            raise
        except sqlite3.Error:
            self._recorder.fail(PERSISTENCE_FAILURE)
            raise
        except Exception:
            self._recorder.fail(UNEXPECTED_FAILURE)
            raise
        try:
            outcome = self._delegate.generate(request, cancellation_token)
        except Exception:
            self._recorder.fail(UNEXPECTED_FAILURE)
            raise
        self._recorder.outcomes.append(outcome)
        return outcome


class _ObservedProcessUserMessage:
    def __init__(self, delegate: Any, recorder: _Recorder) -> None:
        self._delegate = delegate
        self._recorder = recorder

    def execute(self, request: object, cancellation_token: object) -> object:
        try:
            result = self._delegate.execute(request, cancellation_token)
        except Exception:
            self._recorder.fail(UNEXPECTED_FAILURE)
            self._recorder.result_ready.set()
            raise
        self._recorder.results.append(result)
        self._recorder.result_ready.set()
        return result


class _ObservedForegroundScope:
    def __init__(self, delegate: Any, recorder: _Recorder) -> None:
        self._delegate = delegate
        self.process_user_message = _ObservedProcessUserMessage(
            delegate.process_user_message,
            recorder,
        )
        self.recover_processing_run = delegate.recover_processing_run

    def close(self) -> None:
        self._delegate.close()


class _ObservedScopeFactory:
    """Keep the production factory while observing its foreground result."""

    def __init__(
        self,
        delegate: ProductionShellScopeFactory,
        recorder: _Recorder,
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder

    def open_foreground_scope(self) -> _ObservedForegroundScope:
        return _ObservedForegroundScope(
            self._delegate.open_foreground_scope(),
            self._recorder,
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


@dataclass(frozen=True, slots=True)
class _UiObservation:
    result: object | None
    facade_text: str
    qml_text: str


@dataclass(frozen=True, slots=True)
class _DurableGeneration:
    response_text: str
    provider: At016ProviderEvidence
    elapsed_microseconds: int
    provider_metadata: Mapping[str, object]


@contextmanager
def _read_database(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _count(connection: sqlite3.Connection, table: str) -> int:
    allowed = {
        "clarification_requests",
        "constraints",
        "context_packets",
        "conversation_states",
        "conversations",
        "correction_attempts",
        "entity_registry",
        "evaluation_cases",
        "evaluation_runs",
        "memories",
        "memory_revisions",
        "memory_sources",
        "messages",
        "model_requests",
        "model_responses",
        "named_items",
        "pipeline_failures",
        "processing_runs",
        "projects",
        "reference_resolutions",
        "retrieval_exclusions",
        "retrieval_results",
        "tasks",
        "topics",
        "validation_results",
    }
    _require(table in allowed)
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    _require(row is not None)
    return int(row[0])


def _one(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> sqlite3.Row:
    rows = connection.execute(query, parameters).fetchall()
    _require(len(rows) == 1)
    return rows[0]


def _assert_synthetic_oracle(configuration: ApplicationConfiguration) -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    conversation_id = DomainId("68000000-0000-4000-8000-000000000001")
    message_id = DomainId("68000000-0000-4000-8000-000000000002")
    run_id = DomainId("68000000-0000-4000-8000-000000000003")
    state = ConversationState(
        conversation_id,
        None,
        None,
        None,
        None,
        (),
        0,
        now,
    )
    message = Message(
        message_id,
        conversation_id,
        MessageRole.USER,
        USER_MESSAGE,
        now,
        0,
    )
    interpreter = DeterministicInterpretationEngine(
        configuration.context,  # type: ignore[arg-type]
    )
    decision = interpreter.interpret(
        InterpretationRequest(run_id, message, state, now)
    )
    interpretation = decision.interpretation
    _require(len(decision.intent_candidates) == 1)
    _require(decision.intent_candidates[0].evidence.rule_id == "answer")
    _require(interpretation.intent is IntentType.ANSWER)
    _require(interpretation.intent_rule_id == "answer")
    _require(interpretation.expected_output_type is OutputType.TEXT_ANSWER)
    _require(interpretation.confidence == UnitScore("1"))
    _require(len(interpretation.qualifiers) == 1)
    qualifier = interpretation.qualifiers[0]
    _require(qualifier.kind is QualifierKind.EXACTLY)
    _require(qualifier.rule_id == "exactly")
    _require(qualifier.matched_text == "Exactly")
    _require(
        dict(qualifier.captures)
        == {
            "target": "answer context for ai smoke ok",
            "action": "answer",
            "object": "context for ai smoke ok",
        }
    )
    _require(decision.reference_mentions == ())
    _require(decision.proposed_topic_label is None)
    _require(decision.proposed_task_title is None)
    _require(decision.clarification_reason is None)

    committed_state = replace(
        state,
        expected_output_type=OutputType.TEXT_ANSWER,
        version=1,
    )
    constraints = DeterministicConstraintEngine(
        configuration.context,  # type: ignore[arg-type]
        _FixedIds(),
    ).evaluate(
        ConstraintEvaluationRequest(
            message,
            committed_state,
            decision,
            (),
            (),
            (),
            None,
            now,
        )
    )
    _require(len(constraints.constraints) == 2)
    _require(
        tuple(
            (
                item.constraint_type,
                item.source_kind,
                item.normalized_rule,
                item.priority,
                item.resolution_status,
            )
            for item in constraints.constraints
        )
        == (
            (
                ConstraintType.REQUIRED,
                ConstraintSourceKind.CURRENT_MESSAGE,
                "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
                1000,
                ConstraintResolutionStatus.ACTIVE,
            ),
            (
                ConstraintType.FORBIDDEN,
                ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
                "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
                1000,
                ConstraintResolutionStatus.ACTIVE,
            ),
        )
    )
    _require(constraints.conflict_groups == ())
    _require(constraints.response_policy.expected_output_type is OutputType.TEXT_ANSWER)
    _require(constraints.response_policy.text_only is True)
    _require(constraints.response_policy.actions_allowed is False)

    retrieval = DeterministicContextRetriever(_FixedIds()).retrieve(
        RetrievalRequest(
            DomainId("68000000-0000-4000-8000-000000000004"),
            run_id,
            message_id,
            conversation_id,
            None,
            None,
            USER_MESSAGE,
            (),
            UnitScore(str(configuration.context.minimum_relevance_score)),
            configuration.context.retrieved_memory_limit,
            now,
        )
    )
    _require(retrieval.selected == ())
    _require(retrieval.excluded == ())
    _require(retrieval.confidence is None)


def _assert_initial_database(
    database_path: Path,
    preparation: ShellReadyResult,
) -> None:
    _require(preparation.initial_conversation_created is True)
    with _read_database(database_path) as connection:
        for table in (
            "projects",
            "topics",
            "tasks",
            "named_items",
            "entity_registry",
            "memories",
            "memory_sources",
            "memory_revisions",
            "messages",
            "processing_runs",
            "reference_resolutions",
            "constraints",
            "context_packets",
            "retrieval_results",
            "retrieval_exclusions",
            "model_requests",
            "model_responses",
            "validation_results",
            "correction_attempts",
            "clarification_requests",
            "pipeline_failures",
            "evaluation_cases",
            "evaluation_runs",
        ):
            _require(_count(connection, table) == 0)
        _require(_count(connection, "conversations") == 1)
        _require(_count(connection, "conversation_states") == 1)
        conversation = _one(connection, "SELECT * FROM conversations")
        state = _one(connection, "SELECT * FROM conversation_states")
        _require(conversation["id"] == str(preparation.conversation_id))
        _require(conversation["project_id"] is None)
        _require(state["conversation_id"] == conversation["id"])
        _require(state["active_topic_id"] is None)
        _require(state["active_task_id"] is None)
        _require(state["previous_task_id"] is None)
        _require(state["expected_output_type"] is None)
        _require(json.loads(state["topic_stack_json"]) == [])
        _require(state["version"] == 0)


def _assert_pre_provider_database(
    database_path: Path,
    configuration: ApplicationConfiguration,
    generation: GenerationRequest,
) -> None:
    """Assert every durable deterministic outcome before transport starts."""

    with _read_database(database_path) as connection:
        for table in (
            "projects",
            "topics",
            "tasks",
            "named_items",
            "entity_registry",
            "memories",
            "memory_sources",
            "memory_revisions",
            "reference_resolutions",
            "retrieval_results",
            "retrieval_exclusions",
            "model_responses",
            "validation_results",
            "correction_attempts",
            "clarification_requests",
            "pipeline_failures",
            "evaluation_cases",
            "evaluation_runs",
        ):
            _require(_count(connection, table) == 0)
        _require(_count(connection, "conversations") == 1)
        _require(_count(connection, "conversation_states") == 1)
        _require(_count(connection, "messages") == 1)
        _require(_count(connection, "processing_runs") == 1)
        _require(_count(connection, "constraints") == 2)
        _require(_count(connection, "context_packets") == 1)
        _require(_count(connection, "model_requests") == 1)

        message = _one(connection, "SELECT * FROM messages")
        run = _one(connection, "SELECT * FROM processing_runs")
        state = _one(connection, "SELECT * FROM conversation_states")
        packet_row = _one(connection, "SELECT * FROM context_packets")
        request_row = _one(connection, "SELECT * FROM model_requests")
        constraint_rows = connection.execute(
            "SELECT * FROM constraints ORDER BY ordinal"
        ).fetchall()

        _require(message["role"] == "USER")
        _require(message["original_text"].encode("utf-8") == USER_MESSAGE.encode("utf-8"))
        _require(message["sequence_number"] == 0)
        _require(run["id"] == str(generation.processing_run_id))
        _require(run["conversation_id"] == message["conversation_id"])
        _require(run["user_message_id"] == message["id"])
        _require(run["status"] == "GENERATING")
        _require(run["state_version_at_start"] == 0)
        _require(
            run["configuration_fingerprint"]
            == configuration.configuration_fingerprint
        )
        _require(run["completed_at"] is None)

        _require(state["conversation_id"] == run["conversation_id"])
        _require(state["active_topic_id"] is None)
        _require(state["active_task_id"] is None)
        _require(state["previous_task_id"] is None)
        _require(state["expected_output_type"] == "TEXT_ANSWER")
        _require(json.loads(state["topic_stack_json"]) == [])
        _require(state["version"] == 1)

        _require(packet_row["id"] == str(generation.context_packet_id))
        _require(packet_row["processing_run_id"] == run["id"])
        _require(packet_row["message_id"] == message["id"])
        _require(packet_row["schema_version"] == "mvp-context-packet-v2")
        _require(packet_row["prompt_policy_version"] == "mvp-prompt-policy-v2")
        _require(
            packet_row["configuration_fingerprint"]
            == configuration.configuration_fingerprint
        )

        packet = json.loads(packet_row["packet_json"])
        _require(
            set(packet)
            == {
                "active_state",
                "confidence",
                "constraints",
                "references",
                "rendering",
                "request",
                "response_policy",
                "retrieval",
                "schema_version",
                "trace",
                "validation_context",
            }
        )
        _require(packet["schema_version"] == "mvp-context-packet-v2")
        _require(
            packet["request"]
            == {
                "confidence": 1,
                "expected_output_type": "TEXT_ANSWER",
                "intent": "ANSWER",
                "intent_rule_id": "answer",
                "original_text": USER_MESSAGE,
                "qualifiers": [
                    {
                        "kind": "EXACTLY",
                        "matched_text": "Exactly",
                        "rule_id": "exactly",
                    }
                ],
            }
        )
        _require(
            packet["active_state"]
            == {
                "previous_task_id": None,
                "project_id": None,
                "task_id": None,
                "topic_id": None,
                "topic_stack": [],
            }
        )
        _require(packet["references"] == [])
        _require(packet["retrieval"] == [])
        _require(
            packet["confidence"]
            == {
                "interpretation": 1,
                "overall": 1,
                "references": None,
                "retrieval": None,
            }
        )

        packet_constraints = packet["constraints"]
        _require(isinstance(packet_constraints, list))
        _require(len(packet_constraints) == 2)
        _require(
            tuple(
                (
                    item["ordinal"],
                    item["type"],
                    item["source_kind"],
                    item["normalized_rule"],
                    item["priority"],
                    item["status"],
                    item["scope"],
                    item["condition"],
                )
                for item in packet_constraints
            )
            == (
                (
                    0,
                    "REQUIRED",
                    "CURRENT_MESSAGE",
                    "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
                    1000,
                    "ACTIVE",
                    "CURRENT_RESPONSE",
                    None,
                ),
                (
                    1,
                    "FORBIDDEN",
                    "DERIVED_OUTPUT_POLICY",
                    "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
                    1000,
                    "ACTIVE",
                    "CURRENT_RESPONSE",
                    None,
                ),
            )
        )
        _require(
            tuple(
                (
                    row["ordinal"],
                    row["constraint_type"],
                    row["source_kind"],
                    row["normalized_rule"],
                    row["priority"],
                    row["resolution_status"],
                )
                for row in constraint_rows
            )
            == (
                (
                    0,
                    "REQUIRED",
                    "CURRENT_MESSAGE",
                    "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
                    1000,
                    "ACTIVE",
                ),
                (
                    1,
                    "FORBIDDEN",
                    "DERIVED_OUTPUT_POLICY",
                    "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
                    1000,
                    "ACTIVE",
                ),
            )
        )
        _require(
            packet["response_policy"]
            == {
                "absolute_model_generation_cap": 3,
                "correction_limit": 0,
                "model_generation_limit": 1,
                "no_actions": True,
                "output_type": "TEXT_ANSWER",
                "streaming": False,
                "text_only": True,
                "validate_before_display": True,
            }
        )
        _require(
            packet["validation_context"]["output_shape_rule"]
            == {
                "id": "text-answer",
                "output_type": "TEXT_ANSWER",
                "shape": "NON_EMPTY_TEXT",
            }
        )
        _require(packet["validation_context"]["active_topic"] is None)
        _require(
            packet["validation_context"]["rule_set_version"]
            == "mvp-validation-rules-v1"
        )
        _require(
            packet["validation_context"]["action_markers"]
            == ["TOOL_CALL:", "ACTION_EXECUTED:", "IMAGE_RESULT:"]
        )

        rendering = packet["rendering"]
        prompt = generation.rendered_prompt
        rendered_prompt_estimate = conservative_utf8_estimate(prompt)
        _require(rendering["prompt_policy_version"] == "mvp-prompt-policy-v2")
        _require(rendering["token_estimator"] == "conservative_utf8_v1")
        _require(rendering["token_budget"] == 2048)
        _require(rendering["mandatory_estimated_tokens"] == rendered_prompt_estimate)
        _require(rendering["estimated_prompt_tokens"] == rendered_prompt_estimate)
        _require(rendering["included_sections"] == ["CONSTRAINTS"])
        _require(rendering["omitted_sections"] == [])

        trace = packet["trace"]
        _require(trace["processing_run_id"] == run["id"])
        _require(trace["conversation_id"] == run["conversation_id"])
        _require(trace["user_message_id"] == message["id"])
        _require(trace["state_version"] == 1)
        _require(
            trace["configuration_fingerprint"]
            == configuration.configuration_fingerprint
        )

        _require(request_row["id"] == str(generation.model_request_id))
        _require(request_row["processing_run_id"] == run["id"])
        _require(request_row["context_packet_id"] == packet_row["id"])
        _require(request_row["purpose"] == "INITIAL")
        _require(request_row["attempt_number"] == 0)
        _require(request_row["provider"] == "OLLAMA")
        _require(request_row["model_name"] == configuration.model.name)
        _require(request_row["status"] == "IN_FLIGHT")
        _require(request_row["started_at"] is not None)
        _require(request_row["completed_at"] is None)
        _require(request_row["error_code"] is None)
        _require(request_row["safe_error_message"] is None)
        _require(
            request_row["rendered_prompt"].encode("utf-8")
            == generation.rendered_prompt.encode("utf-8")
        )

        request_projection = json.loads(request_row["request_json"])
        _require(
            request_projection["correlation"]
            == {
                "attempt_number": 0,
                "context_packet_id": packet_row["id"],
                "model_request_id": request_row["id"],
                "processing_run_id": run["id"],
            }
        )
        _require(
            request_projection["generation_settings"]
            == {
                "context_window_tokens": 4096,
                "request_timeout_seconds": 60,
                "temperature_decimal": "0",
            }
        )
        _require(
            request_projection["rendering"]
            == {
                "effective_prompt_budget": 2048,
                "estimated_prompt_tokens": rendered_prompt_estimate,
                "included_sections": ["CONSTRAINTS"],
                "omitted_sections": [],
                "prompt_policy_version": "mvp-prompt-policy-v2",
                "render_kind": "INITIAL",
            }
        )
        _require(request_projection["schema_version"] == "mvp-model-request-v1")

        _require(generation.model_name == configuration.model.name)
        _require(generation.attempt_number == 0)
        _require(generation.settings.context_window_tokens == 4096)
        _require(generation.settings.request_timeout_seconds == 60)
        _require(generation.settings.temperature == Decimal("0"))
        _require(prompt.startswith("CONTEXT_FOR_AI_PROMPT/mvp-prompt-policy-v2\n"))
        _require(prompt.endswith("@@CFA/END@@\n"))
        _require(prompt.count("@@CFA/REQUEST/UNTRUSTED_DATA@@") == 1)
        _require(
            prompt.count("@@CFA/VALIDATION_SEMANTICS/TRUSTED_INSTRUCTIONS@@")
            == 1
        )
        _require(prompt.count("@@CFA/CONSTRAINTS/TRUSTED_INSTRUCTIONS@@") == 1)
        _require(prompt.count("@@CFA/CORRECTION/") == 0)
        _require(
            json.dumps(
                {"original_text": USER_MESSAGE},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            in prompt
        )
        validation_semantics = json.loads(
            prompt.split(
                "@@CFA/VALIDATION_SEMANTICS/TRUSTED_INSTRUCTIONS@@\n",
                1,
            )[1].split("\n", 1)[0]
        )
        _require(
            validation_semantics
            == {
                "action_markers": {
                    "forbidden_literals": [
                        "TOOL_CALL:",
                        "ACTION_EXECUTED:",
                        "IMAGE_RESULT:",
                    ],
                    "instruction": (
                        "Do not include any literal listed in forbidden_literals; "
                        "matching uses Unicode NFC and case-folding without "
                        "punctuation or whitespace rewriting."
                    ),
                },
                "output_shape": {
                    "instruction": (
                        "Produce at least one non-empty normalized word of text."
                    ),
                    "rule_id": "text-answer",
                    "shape": "NON_EMPTY_TEXT",
                },
                "topic": None,
            }
        )
        trusted_constraints = json.loads(
            prompt.split(
                "@@CFA/CONSTRAINTS/TRUSTED_INSTRUCTIONS@@\n",
                1,
            )[1].split("\n", 1)[0]
        )
        _require(
            trusted_constraints
            == [
                {
                    "condition": None,
                    "id": constraint_rows[0]["id"],
                    "normalized_rule": (
                        "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK"
                    ),
                    "priority": 1000,
                    "scope": "CURRENT_RESPONSE",
                    "semantic_instruction": (
                        "Include the complete consecutive phrase \"answer context for "
                        "ai smoke ok\" in one sentence; do not use a synonym or "
                        "approximate substitution for that phrase."
                    ),
                    "type": "REQUIRED",
                    "underlying_type": None,
                },
                {
                    "condition": None,
                    "id": constraint_rows[1]["id"],
                    "normalized_rule": "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
                    "priority": 1000,
                    "scope": "CURRENT_RESPONSE",
                    "semantic_instruction": (
                        "Do not include any literal listed in "
                        "action_markers.forbidden_literals in the trusted validation "
                        "semantics."
                    ),
                    "type": "FORBIDDEN",
                    "underlying_type": None,
                },
            ]
        )
        _require(
            request_projection["rendering"]["estimated_prompt_tokens"]
            == conservative_utf8_estimate(prompt)
        )


def _pump_until(
    application: QApplication,
    predicate: Any,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate():
        application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    return True


def _dispose_shell(
    application: QApplication,
    facade: ShellFacade,
    engine: object,
) -> None:
    if facade._controller.active_execution_id is not None:  # type: ignore[attr-defined]
        facade.request_cancellation()
        _pump_until(
            application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
            timeout=10,
        )
    facade.request_shutdown()
    for root in tuple(engine.rootObjects()):  # type: ignore[attr-defined]
        root.close()
    engine.deleteLater()  # type: ignore[attr-defined]
    if facade._controller.active_execution_id is None:  # type: ignore[attr-defined]
        facade.dispose()
        facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def _execute_packaged_qml_submission(
    production_factory: ProductionShellScopeFactory,
    preparation: ShellReadyResult,
    idempotency_keys: object,
    recorder: _Recorder,
) -> _UiObservation:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    _require(isinstance(application, QApplication), UI_FAILURE)
    observed_factory = _ObservedScopeFactory(production_factory, recorder)
    facade = ShellFacade(observed_factory, idempotency_keys)  # type: ignore[arg-type]
    engine: object | None = None
    try:
        try:
            engine = create_qml_engine(facade)
        except StartupError:
            raise _LiveCheckFailure(UI_FAILURE) from None
        root = engine.rootObjects()[0]
        panel = root.findChild(QObject, "chatPanel")
        composer = root.findChild(QObject, "chatComposer")
        assistant_output = root.findChild(QObject, "assistantOutput")
        _require(panel is not None, UI_FAILURE)
        _require(composer is not None, UI_FAILURE)
        _require(assistant_output is not None, UI_FAILURE)
        facade.apply_preparation(preparation)
        _require(facade.route == "CHAT", UI_FAILURE)
        _require(facade.state == "IDLE", UI_FAILURE)
        _require(facade.submit_enabled is True, UI_FAILURE)
        composer.setProperty("text", USER_MESSAGE)
        application.processEvents(
            QEventLoop.ProcessEventsFlag.AllEvents,
            10,
        )
        invoked = QMetaObject.invokeMethod(
            panel,
            "submitCurrentText",
            Qt.ConnectionType.DirectConnection,
        )
        if not invoked or composer.property("text") != "":
            recorder.fail(UI_FAILURE)
        completed = _pump_until(
            application,
            lambda: (
                recorder.result_ready.is_set()
                and facade._controller.active_execution_id is None  # type: ignore[attr-defined]
            ),
            timeout=75,
        )
        if not completed:
            recorder.fail(UI_FAILURE)
        result = recorder.results[0] if len(recorder.results) == 1 else None
        if len(recorder.results) != 1:
            recorder.fail(UNEXPECTED_FAILURE)
        facade_text = facade.assistant_text
        qml_text = str(assistant_output.property("text"))
        if isinstance(result, SucceededResult):
            if facade.state != "SUCCESS" or not facade.submit_enabled:
                recorder.fail(UI_FAILURE)
        return _UiObservation(result, facade_text, qml_text)
    finally:
        if engine is None:
            facade.dispose()
            facade.deleteLater()
        else:
            _dispose_shell(application, facade, engine)


def _failure_for_result(
    result: object | None,
    recorder: _Recorder,
) -> At016Failure | None:
    failure = recorder.first_failure
    if isinstance(result, SucceededResult):
        return failure
    if recorder.outcomes:
        outcome = recorder.outcomes[0]
        if not isinstance(outcome, CompletedGeneration):
            try:
                return retain_first_failure(
                    failure,
                    project_transport_failure(outcome),
                )
            except Exception:
                return retain_first_failure(failure, UNEXPECTED_FAILURE)
    if isinstance(result, ValidationExhaustedResult):
        return retain_first_failure(
            failure,
            At016Failure("VALIDATION", "VALIDATION_EXHAUSTED"),
        )
    if isinstance(result, ConfigurationFailureResult):
        return retain_first_failure(
            failure,
            At016Failure("CONFIGURATION", "CONFIGURATION_INVALID"),
        )
    if isinstance(result, PersistenceFailureResult):
        return retain_first_failure(failure, PERSISTENCE_FAILURE)
    if isinstance(result, CancelledResult):
        return retain_first_failure(
            failure,
            At016Failure("TRANSPORT", "MODEL_CANCELLED"),
        )
    if isinstance(result, ControlledFailureResult):
        transport_codes = {
            "PROVIDER_UNAVAILABLE",
            "MODEL_NOT_FOUND",
            "MODEL_TIMEOUT",
            "INVALID_PROVIDER_RESPONSE",
        }
        if result.error.code.value in transport_codes:
            return retain_first_failure(
                failure,
                At016Failure("TRANSPORT", result.error.code.value),
            )
    return retain_first_failure(failure, UNEXPECTED_FAILURE)


def _extract_durable_generation(database_path: Path) -> _DurableGeneration | None:
    with _read_database(database_path) as connection:
        rows = connection.execute(
            "SELECT response_text, metadata_json FROM model_responses"
        ).fetchall()
    if not rows:
        return None
    _require(len(rows) == 1)
    metadata = json.loads(rows[0]["metadata_json"])
    _require(
        set(metadata)
        == {
            "correlation",
            "elapsed_microseconds",
            "provider_metadata",
            "schema_version",
            "token_usage",
        }
    )
    _require(metadata["schema_version"] == "mvp-completed-generation-v1")
    elapsed = metadata["elapsed_microseconds"]
    _require(isinstance(elapsed, int) and not isinstance(elapsed, bool) and elapsed >= 0)
    provider_metadata = metadata["provider_metadata"]
    _require(isinstance(provider_metadata, dict))
    projected_provider = provider_evidence(provider_metadata)
    return _DurableGeneration(
        rows[0]["response_text"],
        projected_provider,
        elapsed,
        provider_metadata,
    )


def _gateway_elapsed_microseconds(outcome: CompletedGeneration) -> int:
    elapsed: timedelta = outcome.elapsed
    return (
        elapsed.days * 86_400_000_000
        + elapsed.seconds * 1_000_000
        + elapsed.microseconds
    )


def _assert_required_constraint_evidence(
    validation_evidence: object,
    *,
    constraint_id: str,
) -> None:
    _require(isinstance(validation_evidence, list), UNEXPECTED_FAILURE)
    required_checks = tuple(
        item
        for item in validation_evidence
        if isinstance(item, dict)
        and item.get("check_id") == "REQUIRED_CONSTRAINT"
    )
    _require(len(required_checks) == 1, UNEXPECTED_FAILURE)
    required_check = required_checks[0]
    _require(
        set(required_check)
        == {
            "check_id",
            "constraint_id",
            "explanation",
            "matches",
            "missing_predicate",
            "normalized_input",
            "ordinal",
            "outcome",
            "rule_id",
            "severity",
            "violation_code",
            "warning_code",
        },
        UNEXPECTED_FAILURE,
    )
    _require(required_check["check_id"] == "REQUIRED_CONSTRAINT", UNEXPECTED_FAILURE)
    _require(required_check["constraint_id"] == constraint_id, UNEXPECTED_FAILURE)
    _require(required_check["rule_id"] is None, UNEXPECTED_FAILURE)
    _require(required_check["severity"] == "INFO", UNEXPECTED_FAILURE)
    _require(required_check["outcome"] == "PASSED", UNEXPECTED_FAILURE)
    _require(
        required_check["explanation"] == "The deterministic predicate passed.",
        UNEXPECTED_FAILURE,
    )
    _require(required_check["missing_predicate"] is None, UNEXPECTED_FAILURE)
    _require(required_check["violation_code"] is None, UNEXPECTED_FAILURE)
    _require(required_check["warning_code"] is None, UNEXPECTED_FAILURE)

    normalized_input = required_check["normalized_input"]
    _require(isinstance(normalized_input, dict), UNEXPECTED_FAILURE)
    _require(
        set(normalized_input)
        == {
            "candidate_token_count",
            "output_shape",
            "output_type",
            "predicate",
            "sentence_count",
            "topic_terms",
        },
        UNEXPECTED_FAILURE,
    )
    _require(
        isinstance(normalized_input["candidate_token_count"], int)
        and not isinstance(normalized_input["candidate_token_count"], bool)
        and normalized_input["candidate_token_count"] > 0,
        UNEXPECTED_FAILURE,
    )
    _require(
        isinstance(normalized_input["sentence_count"], int)
        and not isinstance(normalized_input["sentence_count"], bool)
        and normalized_input["sentence_count"] > 0,
        UNEXPECTED_FAILURE,
    )
    _require(normalized_input["output_shape"] is None, UNEXPECTED_FAILURE)
    _require(normalized_input["output_type"] is None, UNEXPECTED_FAILURE)
    _require(
        normalized_input["predicate"]
        == "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
        UNEXPECTED_FAILURE,
    )
    _require(normalized_input["topic_terms"] == [], UNEXPECTED_FAILURE)

    matches = required_check["matches"]
    _require(isinstance(matches, list) and bool(matches), UNEXPECTED_FAILURE)
    _require(
        all(
            isinstance(match, dict)
            and set(match) == {"sentence_ordinal", "source_end", "source_start"}
            and isinstance(match["source_start"], int)
            and not isinstance(match["source_start"], bool)
            and isinstance(match["source_end"], int)
            and not isinstance(match["source_end"], bool)
            and 0 <= match["source_start"] < match["source_end"]
            for match in matches
        ),
        UNEXPECTED_FAILURE,
    )
    _require(
        any(
            isinstance(match["sentence_ordinal"], int)
            and not isinstance(match["sentence_ordinal"], bool)
            and match["sentence_ordinal"] >= 0
            for match in matches
        ),
        UNEXPECTED_FAILURE,
    )


def _assert_success_lineage(
    database_path: Path,
    configuration: ApplicationConfiguration,
    recorder: _Recorder,
    observation: _UiObservation,
    durable: _DurableGeneration,
) -> tuple[str, ...]:
    result = observation.result
    _require(isinstance(result, SucceededResult))
    _require(len(recorder.requests) == 1)
    _require(len(recorder.outcomes) == 1)
    outcome = recorder.outcomes[0]
    _require(isinstance(outcome, CompletedGeneration))
    generation = recorder.requests[0]

    with _read_database(database_path) as connection:
        expected_counts = {
            "conversations": 1,
            "conversation_states": 1,
            "messages": 2,
            "processing_runs": 1,
            "constraints": 2,
            "context_packets": 1,
            "model_requests": 1,
            "model_responses": 1,
            "validation_results": 1,
        }
        for table, expected in expected_counts.items():
            _require(_count(connection, table) == expected)
        for table in (
            "projects",
            "topics",
            "tasks",
            "named_items",
            "entity_registry",
            "memories",
            "memory_sources",
            "memory_revisions",
            "reference_resolutions",
            "retrieval_results",
            "retrieval_exclusions",
            "correction_attempts",
            "clarification_requests",
            "pipeline_failures",
            "evaluation_cases",
            "evaluation_runs",
        ):
            _require(_count(connection, table) == 0)

        messages = connection.execute(
            "SELECT * FROM messages ORDER BY sequence_number"
        ).fetchall()
        run = _one(connection, "SELECT * FROM processing_runs")
        state = _one(connection, "SELECT * FROM conversation_states")
        packet = _one(connection, "SELECT * FROM context_packets")
        request = _one(connection, "SELECT * FROM model_requests")
        response = _one(connection, "SELECT * FROM model_responses")
        validation = _one(connection, "SELECT * FROM validation_results")
        required_constraint_rows = connection.execute(
            """
            SELECT id FROM constraints
            WHERE constraint_type = 'REQUIRED'
              AND resolution_status = 'ACTIVE'
              AND normalized_rule = ?
            """,
            ("MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",),
        ).fetchall()
        _require(len(required_constraint_rows) == 1)
        required_constraint_id = str(required_constraint_rows[0]["id"])
        persisted_validation = SQLiteValidationRepository(connection).get(
            result.latest_validation_result.id
        )
        _require(
            persisted_validation == result.latest_validation_result,
            LINEAGE_FAILURE,
        )

        _require(messages[0]["id"] == str(result.user_message_id))
        _require(messages[0]["role"] == "USER")
        _require(messages[0]["sequence_number"] == 0)
        _require(
            messages[0]["original_text"].encode("utf-8")
            == USER_MESSAGE.encode("utf-8")
        )
        _require(messages[1]["id"] == str(result.assistant_message_id))
        _require(messages[1]["role"] == "ASSISTANT")
        _require(messages[1]["sequence_number"] == 1)

        _require(run["id"] == str(result.processing_run_id))
        _require(run["user_message_id"] == messages[0]["id"])
        _require(run["status"] == "SUCCEEDED")
        _require(run["state_version_at_start"] == 0)
        _require(run["configuration_fingerprint"] == configuration.configuration_fingerprint)
        _require(run["completed_at"] is not None)
        _require(state["conversation_id"] == run["conversation_id"])
        _require(state["active_topic_id"] is None)
        _require(state["active_task_id"] is None)
        _require(state["previous_task_id"] is None)
        _require(state["expected_output_type"] == "TEXT_ANSWER")
        _require(json.loads(state["topic_stack_json"]) == [])
        _require(state["version"] == 1)

        _require(packet["id"] == str(result.context_packet_id))
        _require(packet["processing_run_id"] == run["id"])
        _require(packet["message_id"] == messages[0]["id"])
        _require(request["id"] == str(generation.model_request_id))
        _require(request["processing_run_id"] == run["id"])
        _require(request["context_packet_id"] == packet["id"])
        _require(request["purpose"] == "INITIAL")
        _require(request["attempt_number"] == 0)
        _require(request["status"] == "SUCCEEDED")
        _require(request["model_name"] == configuration.model.name)
        _require(request["error_code"] is None)
        _require(request["safe_error_message"] is None)
        _require(response["model_request_id"] == request["id"])
        _require(response["assistant_message_id"] == messages[1]["id"])
        _require(validation["model_response_id"] == response["id"])
        _require(validation["id"] == str(result.latest_validation_result.id))
        _require(validation["status"] == "PASSED")
        _require(validation["score"] == 1.0)
        _require(json.loads(validation["violations_json"]) == [])
        validation_evidence = json.loads(validation["evidence_json"])
        _assert_required_constraint_evidence(
            validation_evidence,
            constraint_id=required_constraint_id,
        )

        metadata = json.loads(response["metadata_json"])
        correlation = metadata["correlation"]
        _require(
            correlation
            == {
                "attempt_number": 0,
                "context_packet_id": packet["id"],
                "model_request_id": request["id"],
                "model_response_id": response["id"],
                "processing_run_id": run["id"],
            }
        )
        _require(metadata["elapsed_microseconds"] == durable.elapsed_microseconds)
        _require(
            durable.elapsed_microseconds
            == _gateway_elapsed_microseconds(outcome)
        )
        _require(
            set(durable.provider_metadata)
            == {
                "provider",
                "provider_version",
                "model_identity",
                "model_tag",
                "cloud_disable_source",
                "done_reason",
                "total_duration_ns",
                "load_duration_ns",
                "prompt_eval_duration_ns",
                "eval_duration_ns",
            }
        )
        _require(durable.provider_metadata["provider"] == "ollama")
        _require(durable.provider_metadata["model_identity"] == configuration.model.name)
        _require(
            durable.provider_metadata["model_tag"]
            == model_evidence(configuration.model.name).tag
        )
        _require(
            durable.provider_metadata["cloud_disable_source"]
            in {"env", "config", "both"}
        )

        byte_values = (
            outcome.response_text,
            durable.response_text,
            response["response_text"],
            messages[1]["original_text"],
            result.assistant_text,
            observation.facade_text,
            observation.qml_text,
        )
        expected_bytes = byte_values[0].encode("utf-8")
        _require(all(value.encode("utf-8") == expected_bytes for value in byte_values))

        request_projection = json.loads(request["request_json"])
        _require(request_projection["correlation"]["attempt_number"] == 0)
        _require(request_projection["rendering"]["effective_prompt_budget"] == 2048)
        _require(request_projection["rendering"]["render_kind"] == "INITIAL")
        _require(request_projection["rendering"]["omitted_sections"] == [])
        _require(
            request["rendered_prompt"].encode("utf-8")
            == generation.rendered_prompt.encode("utf-8")
        )

        return (
            packet["packet_json"],
            request["rendered_prompt"],
            response["response_text"],
            messages[1]["original_text"],
        )


def _collect_private_durable_values(database_path: Path) -> tuple[str, ...]:
    values: list[str] = []
    with _read_database(database_path) as connection:
        for query in (
            "SELECT packet_json FROM context_packets",
            "SELECT rendered_prompt FROM model_requests",
            "SELECT response_text FROM model_responses",
            "SELECT original_text FROM messages",
        ):
            values.extend(
                row[0]
                for row in connection.execute(query).fetchall()
                if isinstance(row[0], str) and row[0]
            )
    return tuple(values)


def _flush_trace_log() -> None:
    for handler in tuple(logging.getLogger("context_for_ai").handlers):
        handler.flush()


def _load_trace_records(log_path: Path) -> tuple[dict[str, object], ...]:
    _flush_trace_log()
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        records = tuple(json.loads(line) for line in lines)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _LiveCheckFailure(TRACE_FAILURE) from None
    _require(bool(records), TRACE_FAILURE)
    _require(all(isinstance(record, dict) for record in records), TRACE_FAILURE)
    _require(all(set(record) == TRACE_KEYS for record in records), TRACE_FAILURE)
    return records


def _assert_trace_sequence(
    records: tuple[dict[str, object], ...],
    configuration: ApplicationConfiguration,
    result: SucceededResult,
    database_path: Path,
) -> None:
    run_records = tuple(
        record
        for record in records
        if record["processing_run_id"] == str(result.processing_run_id)
    )
    _require(
        tuple(record["event_name"] for record in run_records)
        == EXPECTED_TRACE_NAMES,
        TRACE_FAILURE,
    )
    _require(
        tuple(record["stage"] for record in run_records)
        == EXPECTED_TRACE_STAGES,
        TRACE_FAILURE,
    )
    _require(
        all(
            record["configuration_fingerprint"]
            == configuration.configuration_fingerprint
            for record in records
        ),
        TRACE_FAILURE,
    )
    _require(all(record["level"] == "INFO" for record in records), TRACE_FAILURE)
    _require(
        all(
            isinstance(record["timestamp"], str)
            and record["timestamp"].endswith("Z")
            for record in records
        ),
        TRACE_FAILURE,
    )
    common = {
        "conversation_id": str(result.current_state.conversation_id),
        "user_message_id": str(result.user_message_id),
        "processing_run_id": str(result.processing_run_id),
    }
    for record in run_records:
        _require(
            all(record[key] == value for key, value in common.items()),
            TRACE_FAILURE,
        )
        _require(record["clarification_request_id"] is None, TRACE_FAILURE)
        _require(record["memory_id"] is None, TRACE_FAILURE)
        _require(record["memory_revision_id"] is None, TRACE_FAILURE)
        _require(record["correction_attempt_number"] is None, TRACE_FAILURE)
        _require(record["error_type"] is None, TRACE_FAILURE)

    for index in range(1):
        _require(run_records[index]["context_packet_id"] is None, TRACE_FAILURE)
        _require(run_records[index]["model_request_id"] is None, TRACE_FAILURE)
        _require(run_records[index]["model_response_id"] is None, TRACE_FAILURE)
        _require(run_records[index]["validation_result_id"] is None, TRACE_FAILURE)
    for index in range(1, 6):
        _require(
            run_records[index]["context_packet_id"] == str(result.context_packet_id),
            TRACE_FAILURE,
        )
        _require(run_records[index]["model_request_id"] is None, TRACE_FAILURE)
        _require(run_records[index]["model_response_id"] is None, TRACE_FAILURE)
        _require(run_records[index]["validation_result_id"] is None, TRACE_FAILURE)

    request_id = run_records[6]["model_request_id"]
    response_id = run_records[7]["model_response_id"]
    validation_id = run_records[8]["validation_result_id"]
    _require(isinstance(request_id, str) and bool(request_id), TRACE_FAILURE)
    _require(isinstance(response_id, str) and bool(response_id), TRACE_FAILURE)
    _require(isinstance(validation_id, str) and bool(validation_id), TRACE_FAILURE)
    for index in range(6, 10):
        _require(
            run_records[index]["context_packet_id"] == str(result.context_packet_id),
            TRACE_FAILURE,
        )
        _require(run_records[index]["model_request_id"] == request_id, TRACE_FAILURE)
    _require(run_records[6]["model_response_id"] is None, TRACE_FAILURE)
    _require(run_records[6]["validation_result_id"] is None, TRACE_FAILURE)
    _require(run_records[7]["validation_result_id"] is None, TRACE_FAILURE)
    _require(run_records[8]["model_response_id"] == response_id, TRACE_FAILURE)
    _require(run_records[9]["model_response_id"] == response_id, TRACE_FAILURE)
    _require(run_records[9]["validation_result_id"] == validation_id, TRACE_FAILURE)
    _require(
        validation_id == str(result.latest_validation_result.id),
        TRACE_FAILURE,
    )
    with _read_database(database_path) as connection:
        durable_ids = _one(
            connection,
            """
            SELECT
                model_requests.id AS request_id,
                model_responses.id AS response_id,
                validation_results.id AS validation_id
            FROM model_requests
            JOIN model_responses
                ON model_responses.model_request_id = model_requests.id
            JOIN validation_results
                ON validation_results.model_response_id = model_responses.id
            """,
        )
    _require(request_id == durable_ids["request_id"], TRACE_FAILURE)
    _require(response_id == durable_ids["response_id"], TRACE_FAILURE)
    _require(validation_id == durable_ids["validation_id"], TRACE_FAILURE)


def _assert_trace_redaction(log_path: Path, private_values: tuple[str, ...]) -> None:
    try:
        data = log_path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError):
        raise _LiveCheckFailure(REDACTION_FAILURE) from None
    for value in private_values:
        if value and value.encode("utf-8") in data:
            raise _LiveCheckFailure(REDACTION_FAILURE) from None
    folded = text.casefold()
    for fragment in (
        ".env",
        "http://",
        "https://",
        "authorization",
        "cookie",
        "hostname",
        "username",
        "machine_id",
        "machine-id",
    ):
        if fragment in folded:
            raise _LiveCheckFailure(REDACTION_FAILURE) from None


def _configuration_and_model(
    application_root: Path,
    loader_environment: Mapping[str, str],
) -> tuple[ApplicationConfiguration, At016ModelEvidence]:
    configuration = load_configuration(
        application_root=application_root,
        environ=loader_environment,
    )
    return configuration, model_evidence(configuration.model.name)


def _retain_observed_failure(
    current: At016Failure | None,
    operation: Any,
    *,
    default: At016Failure,
) -> tuple[At016Failure | None, object | None]:
    try:
        return current, operation()
    except _LiveCheckFailure as error:
        return retain_first_failure(current, error.failure), None
    except sqlite3.Error:
        return retain_first_failure(current, PERSISTENCE_FAILURE), None
    except Exception:
        return retain_first_failure(current, default), None


def test_task_0018_at_016_complete_local_ollama_pipeline(
    tmp_path: Path,
) -> None:
    gate = evaluate_at_016_gate(os.environ)
    if gate.opt_in is OllamaLiveOptIn.ABSENT:
        pytest.skip("AT-016 requires exact explicit local Ollama opt-in.")
    if gate.opt_in is OllamaLiveOptIn.INVALID:
        pytest.fail("AT-016_INVALID_OPT_IN", pytrace=False)

    prerequisites: At016Prerequisites = validated_prerequisites(
        default_non_live_suite="PASSED",
        at_001_through_at_015="PASSED",
    )
    failure = gate.failure
    configuration: ApplicationConfiguration | None = None
    model: At016ModelEvidence | None = None
    provider: At016ProviderEvidence | None = None
    gateway_elapsed_microseconds: int | None = None
    startup: object | None = None
    observation: _UiObservation | None = None
    durable: _DurableGeneration | None = None
    recorder = _Recorder()
    private_values: list[str] = [USER_MESSAGE, SMOKE_SENTINEL]
    application_root = tmp_path / "at-016-application-root"

    if failure is None:
        try:
            shutil.copytree(FIXTURE_ROOT, application_root)
            configuration, model = _configuration_and_model(
                application_root,
                gate.loader_environment,
            )
            private_values.extend(
                (
                    str(application_root.resolve()),
                    str(configuration.app.data_directory),
                    str(configuration.logging.directory),
                    configuration.model.base_url,
                )
            )
            _assert_synthetic_oracle(configuration)
        except ConfigurationError:
            failure = At016Failure("CONFIGURATION", "CONFIGURATION_INVALID")
        except _LiveCheckFailure as error:
            failure = error.failure
        except Exception:
            failure = At016Failure("STARTUP", "STARTUP_FAILED")

    if failure is None and configuration is not None:
        try:
            startup = bootstrap_application(
                application_root=application_root,
                environ=gate.loader_environment,
            )
            production_factory = startup.scope_factory
            _require(
                isinstance(production_factory, ProductionShellScopeFactory),
                At016Failure("STARTUP", "STARTUP_FAILED"),
            )
            real_gateway = production_factory._model_gateway  # type: ignore[attr-defined]
            _require(
                real_gateway.__class__.__module__
                == "context_for_ai.infrastructure.ollama.provider"
                and real_gateway.__class__.__name__ == "OllamaModelProvider",
                At016Failure("STARTUP", "STARTUP_FAILED"),
            )
            preparation = prepare_application_shell(production_factory)
            _require(
                isinstance(preparation, ShellReadyResult),
                At016Failure("STARTUP", "STARTUP_FAILED"),
            )
            _assert_initial_database(startup.database_path, preparation)
            observed_gateway = _ObservedGateway(
                real_gateway,
                recorder,
                lambda request: _assert_pre_provider_database(
                    startup.database_path,
                    configuration,
                    request,
                ),
            )
            production_factory._model_gateway = observed_gateway  # type: ignore[attr-defined]
            observation = _execute_packaged_qml_submission(
                production_factory,
                preparation,
                startup.idempotency_keys,
                recorder,
            )
            failure = _failure_for_result(observation.result, recorder)
        except ConfigurationError:
            failure = retain_first_failure(
                failure,
                At016Failure("CONFIGURATION", "CONFIGURATION_INVALID"),
            )
        except StartupError:
            failure = retain_first_failure(
                failure,
                At016Failure("STARTUP", "STARTUP_FAILED"),
            )
        except _LiveCheckFailure as error:
            failure = retain_first_failure(failure, error.failure)
        except sqlite3.Error:
            failure = retain_first_failure(failure, PERSISTENCE_FAILURE)
        except Exception:
            failure = retain_first_failure(failure, UNEXPECTED_FAILURE)

    if startup is not None:
        database_path = startup.database_path  # type: ignore[attr-defined]
        failure, extracted = _retain_observed_failure(
            failure,
            lambda: _extract_durable_generation(database_path),
            default=LINEAGE_FAILURE,
        )
        if isinstance(extracted, _DurableGeneration):
            durable = extracted
            provider = durable.provider
            gateway_elapsed_microseconds = durable.elapsed_microseconds
            private_values.append(durable.response_text)

        failure, collected = _retain_observed_failure(
            failure,
            lambda: _collect_private_durable_values(database_path),
            default=PERSISTENCE_FAILURE,
        )
        if isinstance(collected, tuple):
            private_values.extend(collected)

    if (
        startup is not None
        and configuration is not None
        and observation is not None
        and isinstance(observation.result, SucceededResult)
    ):
        if durable is None:
            failure = retain_first_failure(failure, LINEAGE_FAILURE)
        else:
            failure, lineage_private = _retain_observed_failure(
                failure,
                lambda: _assert_success_lineage(
                    startup.database_path,  # type: ignore[attr-defined]
                    configuration,
                    recorder,
                    observation,
                    durable,
                ),
                default=LINEAGE_FAILURE,
            )
            if isinstance(lineage_private, tuple):
                private_values.extend(lineage_private)

        log_path = configuration.logging.directory / "context_for_ai.log"
        failure, loaded_records = _retain_observed_failure(
            failure,
            lambda: _load_trace_records(log_path),
            default=TRACE_FAILURE,
        )
        if isinstance(loaded_records, tuple):
            failure, _ = _retain_observed_failure(
                failure,
                lambda: _assert_trace_sequence(
                    loaded_records,
                    configuration,
                    observation.result,
                    startup.database_path,  # type: ignore[attr-defined]
                ),
                default=TRACE_FAILURE,
            )
            failure, _ = _retain_observed_failure(
                failure,
                lambda: _assert_trace_redaction(
                    log_path,
                    tuple(private_values),
                ),
                default=REDACTION_FAILURE,
            )

    evidence = finalize_evidence(
        recorded_at=datetime.now(UTC),
        prerequisites=prerequisites,
        configuration_fingerprint=(
            None
            if configuration is None
            else configuration.configuration_fingerprint
        ),
        failure=failure,
        gateway_elapsed_microseconds=gateway_elapsed_microseconds,
        model=model,
        provider=provider,
    )
    try:
        write_evidence(
            EVIDENCE_DIRECTORY,
            evidence,
            gate=gate,
            prohibited_values=tuple(private_values),
        )
    except At016EvidenceWriteError:
        pytest.fail("EVIDENCE_WRITE_FAILED", pytrace=False)

    if evidence.failure is not None:
        pytest.fail(
            f"AT-016_FAILED_{evidence.failure.stage}_{evidence.failure.code}",
            pytrace=False,
        )
