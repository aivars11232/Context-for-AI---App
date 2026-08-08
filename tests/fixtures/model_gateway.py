"""Deterministic, fully buffered test adapter for the inward model gateway."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from threading import Event, Lock

from context_for_ai.domain.ports import (
    CancellationToken,
    CompletedGeneration,
    GenerationOutcome,
    GenerationRequest,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)


MOCK_MODEL_SCRIPT_VERSION = "mock-model-provider-v1"

_SCRIPTED_OUTCOME_TYPES = (
    CompletedGeneration,
    ProviderUnavailableFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    InvalidProviderResponseFailure,
)
_OUTCOME_TYPES = (*_SCRIPTED_OUTCOME_TYPES, ModelCancelledFailure)


class MockModelFixtureError(AssertionError):
    """Report a malformed, mismatched, or exhausted deterministic test script."""


@unique
class MockCheckpoint(StrEnum):
    """Content-free terminal checkpoint behavior for one scripted call."""

    IMMEDIATE = "IMMEDIATE"
    HELD = "HELD"


@dataclass(frozen=True, slots=True)
class MockGenerationStep:
    """One exact expected request and its supplied non-cancellation outcome."""

    expected_request: GenerationRequest
    checkpoint: MockCheckpoint
    terminal_outcome: GenerationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.expected_request, GenerationRequest):
            raise MockModelFixtureError(
                "MockGenerationStep.expected_request must be a GenerationRequest."
            )
        if not isinstance(self.checkpoint, MockCheckpoint):
            raise MockModelFixtureError(
                "MockGenerationStep.checkpoint must be IMMEDIATE or HELD."
            )
        if not isinstance(self.terminal_outcome, _SCRIPTED_OUTCOME_TYPES):
            raise MockModelFixtureError(
                "MockGenerationStep.terminal_outcome must be a supplied success "
                "or non-cancellation failure."
            )


@dataclass(frozen=True, slots=True)
class MockModelScript:
    """One immutable ordered mock-model-provider-v1 call script."""

    schema_version: str
    steps: tuple[MockGenerationStep, ...]

    def __post_init__(self) -> None:
        if self.schema_version != MOCK_MODEL_SCRIPT_VERSION:
            raise MockModelFixtureError(
                "MockModelScript.schema_version must be mock-model-provider-v1."
            )
        if isinstance(self.steps, (str, bytes)):
            raise MockModelFixtureError(
                "MockModelScript.steps must be an ordered collection of steps."
            )
        steps = tuple(self.steps)
        if any(not isinstance(step, MockGenerationStep) for step in steps):
            raise MockModelFixtureError(
                "MockModelScript.steps must contain only MockGenerationStep values."
            )
        object.__setattr__(self, "steps", steps)


@dataclass(frozen=True, slots=True)
class MockCallRecord:
    """One immutable terminal observation with no retained cancellation token."""

    ordinal: int
    script_step_index: int | None
    request: GenerationRequest
    outcome: GenerationOutcome

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ordinal, int)
            or isinstance(self.ordinal, bool)
            or self.ordinal < 0
        ):
            raise MockModelFixtureError(
                "MockCallRecord.ordinal must be a non-negative integer."
            )
        if self.script_step_index is not None and (
            not isinstance(self.script_step_index, int)
            or isinstance(self.script_step_index, bool)
            or self.script_step_index < 0
        ):
            raise MockModelFixtureError(
                "MockCallRecord.script_step_index must be non-negative or null."
            )
        if not isinstance(self.request, GenerationRequest):
            raise MockModelFixtureError(
                "MockCallRecord.request must be a GenerationRequest."
            )
        if not isinstance(self.outcome, _OUTCOME_TYPES):
            raise MockModelFixtureError(
                "MockCallRecord.outcome must be a GenerationOutcome value."
            )


@dataclass(slots=True)
class _HeldCheckpoint:
    reached: Event
    released: Event


class MockCheckpointController:
    """Coordinate content-free held checkpoints without polling or real sleeps."""

    def __init__(self, held_step_indices: tuple[int, ...]) -> None:
        self._checkpoints = {
            step_index: _HeldCheckpoint(Event(), Event())
            for step_index in held_step_indices
        }

    def wait_until_held(
        self,
        step_index: int,
        bounded_test_timeout: float,
    ) -> None:
        """Wait only as a bounded test guard until one held step is reached."""

        checkpoint = self._checkpoint(step_index)
        if (
            not isinstance(bounded_test_timeout, (int, float))
            or isinstance(bounded_test_timeout, bool)
            or bounded_test_timeout <= 0
        ):
            raise MockModelFixtureError(
                "bounded_test_timeout must be a positive test-only duration."
            )
        if not checkpoint.reached.wait(float(bounded_test_timeout)):
            raise MockModelFixtureError(
                f"Mock step {step_index} did not reach its held checkpoint."
            )

    def release(self, step_index: int) -> None:
        """Release one held step; this operation carries no response content."""

        self._checkpoint(step_index).released.set()

    def _hold(self, step_index: int) -> None:
        checkpoint = self._checkpoint(step_index)
        checkpoint.reached.set()
        checkpoint.released.wait()

    def _checkpoint(self, step_index: int) -> _HeldCheckpoint:
        if (
            not isinstance(step_index, int)
            or isinstance(step_index, bool)
            or step_index not in self._checkpoints
        ):
            raise MockModelFixtureError(
                f"Mock step {step_index!r} is not a held checkpoint."
            )
        return self._checkpoints[step_index]


class DeterministicCancellationToken:
    """Thread-safe monotonic cancellation token owned by one deterministic test."""

    def __init__(self, *, cancelled: bool = False) -> None:
        if not isinstance(cancelled, bool):
            raise MockModelFixtureError(
                "DeterministicCancellationToken.cancelled must be boolean."
            )
        self._cancelled = Event()
        if cancelled:
            self._cancelled.set()

    def cancel(self) -> None:
        """Move the token monotonically to cancelled."""

        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Return the current cancellation observation."""

        return self._cancelled.is_set()


class MockModelProvider:
    """Consume one immutable script through the provider-independent gateway port."""

    def __init__(self, script: MockModelScript) -> None:
        if not isinstance(script, MockModelScript):
            raise MockModelFixtureError(
                "MockModelProvider requires a typed immutable script."
            )
        self._script = script
        self._lock = Lock()
        self._next_step_index = 0
        self._call_records: list[MockCallRecord] = []
        self._checkpoint_controller = MockCheckpointController(
            tuple(
                index
                for index, step in enumerate(script.steps)
                if step.checkpoint is MockCheckpoint.HELD
            )
        )

    @property
    def checkpoint_controller(self) -> MockCheckpointController:
        """Expose the content-free held-checkpoint test controller."""

        return self._checkpoint_controller

    @property
    def call_snapshot(self) -> tuple[MockCallRecord, ...]:
        """Return one immutable ordered snapshot of terminal call observations."""

        with self._lock:
            return tuple(self._call_records)

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> GenerationOutcome:
        """Return one complete scripted outcome with canonical cancellation ordering."""

        if not isinstance(request, GenerationRequest):
            raise MockModelFixtureError(
                "MockModelProvider request must be a GenerationRequest."
            )
        if self._is_cancelled(cancellation_token):
            outcome = ModelCancelledFailure()
            self._record(request, None, outcome)
            return outcome

        step_index, step = self._reserve_matching_step(request)
        if step.checkpoint is MockCheckpoint.HELD:
            self._checkpoint_controller._hold(step_index)

        outcome: GenerationOutcome
        if self._is_cancelled(cancellation_token):
            outcome = ModelCancelledFailure()
        else:
            outcome = step.terminal_outcome
        self._record(request, step_index, outcome)
        return outcome

    def _reserve_matching_step(
        self,
        request: GenerationRequest,
    ) -> tuple[int, MockGenerationStep]:
        with self._lock:
            step_index = self._next_step_index
            if step_index >= len(self._script.steps):
                raise MockModelFixtureError(
                    f"Mock model script exhausted before call {step_index}."
                )
            step = self._script.steps[step_index]
            if request != step.expected_request:
                raise MockModelFixtureError(
                    f"GenerationRequest did not match mock script step {step_index}."
                )
            self._next_step_index += 1
            return step_index, step

    def _record(
        self,
        request: GenerationRequest,
        script_step_index: int | None,
        outcome: GenerationOutcome,
    ) -> None:
        with self._lock:
            record = MockCallRecord(
                ordinal=len(self._call_records),
                script_step_index=script_step_index,
                request=request,
                outcome=outcome,
            )
            self._call_records.append(record)

    @staticmethod
    def _is_cancelled(cancellation_token: CancellationToken) -> bool:
        is_cancelled = getattr(cancellation_token, "is_cancelled", None)
        if not callable(is_cancelled):
            raise MockModelFixtureError(
                "MockModelProvider requires a CancellationToken."
            )
        observation = is_cancelled()
        if not isinstance(observation, bool):
            raise MockModelFixtureError(
                "CancellationToken.is_cancelled() must return boolean."
            )
        return observation


__all__ = [
    "DeterministicCancellationToken",
    "MOCK_MODEL_SCRIPT_VERSION",
    "MockCallRecord",
    "MockCheckpoint",
    "MockCheckpointController",
    "MockGenerationStep",
    "MockModelFixtureError",
    "MockModelProvider",
    "MockModelScript",
]
