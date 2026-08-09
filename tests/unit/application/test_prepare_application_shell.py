"""Unit coverage for deterministic pre-QML shell preparation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Iterator

from context_for_ai.application import (
    PrepareApplicationShellRequest,
    RecoveryRequiredResult,
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
    ShellReadyResult,
)
from context_for_ai.application.prepare_application_shell import (
    PrepareApplicationShellService,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Project
from context_for_ai.domain.enums import ProcessingRunStatus, ProjectStatus
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import Setting
from context_for_ai.domain.value_objects import DomainId


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"51000000-0000-4000-8000-{number:012x}")


def conversation(
    number: int,
    *,
    project_id: DomainId | None = None,
    updated_at: datetime = NOW,
) -> Conversation:
    return Conversation(identifier(number), project_id, None, NOW, updated_at)


def state(conversation_id: DomainId) -> ConversationState:
    return ConversationState(
        conversation_id,
        None,
        None,
        None,
        None,
        (),
        0,
        NOW,
    )


class FakeProjects:
    def __init__(self, *records: Project) -> None:
        self.records = tuple(records)
        self.list_calls: list[ProjectStatus] = []

    def list_by_status(self, status: ProjectStatus) -> tuple[Project, ...]:
        self.list_calls.append(status)
        return tuple(project for project in self.records if project.status is status)


class FakeConversations:
    def __init__(self, *records: Conversation) -> None:
        self.records = {record.id: record for record in records}
        self.get_calls: list[DomainId] = []
        self.list_calls: list[DomainId | None] = []
        self.add_calls = 0

    def get(self, conversation_id: DomainId) -> Conversation | None:
        self.get_calls.append(conversation_id)
        return self.records.get(conversation_id)

    def list_for_project(
        self,
        project_id: DomainId | None,
    ) -> tuple[Conversation, ...]:
        self.list_calls.append(project_id)
        return tuple(
            record
            for record in self.records.values()
            if record.project_id == project_id
        )

    def add(self, record: Conversation) -> None:
        self.add_calls += 1
        self.records[record.id] = record

    def capture(self) -> tuple[dict[DomainId, Conversation], int]:
        return dict(self.records), self.add_calls

    def restore(
        self,
        snapshot: tuple[dict[DomainId, Conversation], int],
    ) -> None:
        self.records, self.add_calls = snapshot


class FakeStates:
    def __init__(self, *records: ConversationState) -> None:
        self.records = {record.conversation_id: record for record in records}
        self.get_calls: list[DomainId] = []
        self.add_calls = 0
        self.fail_add = False

    def get(self, conversation_id: DomainId) -> ConversationState | None:
        self.get_calls.append(conversation_id)
        return self.records.get(conversation_id)

    def add(self, record: ConversationState) -> None:
        self.add_calls += 1
        if self.fail_add:
            raise PersistenceError("Injected state write failure.")
        self.records[record.conversation_id] = record

    def capture(self) -> tuple[dict[DomainId, ConversationState], int]:
        return dict(self.records), self.add_calls

    def restore(
        self,
        snapshot: tuple[dict[DomainId, ConversationState], int],
    ) -> None:
        self.records, self.add_calls = snapshot


class FakeRuns:
    def __init__(self, active: ProcessingRun | None = None) -> None:
        self.active = active
        self.calls = 0
        self.fail = False

    def get_non_terminal(self) -> ProcessingRun | None:
        self.calls += 1
        if self.fail:
            raise PersistenceError("Injected preflight read failure.")
        return self.active


class FakeSettings:
    def __init__(self, value: object | None = None, *, present: bool = False) -> None:
        self.value = value
        self.present = present
        self.get_calls = 0
        self.set_calls = 0

    def get(self, key: str) -> Setting | None:
        assert key == "ui.last_selected_conversation_id"
        self.get_calls += 1
        if not self.present:
            return None
        return Setting(key, self.value, NOW)  # type: ignore[arg-type]

    def set(self, **_: object) -> Setting:
        self.set_calls += 1
        raise AssertionError("Shell preparation must not write settings.")


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class FixedIds:
    def __init__(self, value: DomainId) -> None:
        self.value = value
        self.calls = 0

    def new_id(self) -> DomainId:
        self.calls += 1
        return self.value


class SnapshotTransactions:
    def __init__(self, *repositories: object) -> None:
        self.repositories = repositories
        self.entries = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.entries += 1
        snapshots = tuple(
            (repository, repository.capture())
            for repository in self.repositories
            if hasattr(repository, "capture")
        )
        try:
            yield
        except BaseException:
            for repository, snapshot in reversed(snapshots):
                repository.restore(snapshot)
            raise


def build_service(
    *,
    projects: FakeProjects | None = None,
    conversations: FakeConversations | None = None,
    states: FakeStates | None = None,
    runs: FakeRuns | None = None,
    settings: FakeSettings | None = None,
    clock: FixedClock | None = None,
    ids: FixedIds | None = None,
) -> tuple[
    PrepareApplicationShellService,
    FakeProjects,
    FakeConversations,
    FakeStates,
    FakeRuns,
    FakeSettings,
    SnapshotTransactions,
    FixedClock,
    FixedIds,
]:
    project_repository = projects or FakeProjects()
    conversation_repository = conversations or FakeConversations()
    state_repository = states or FakeStates()
    run_repository = runs or FakeRuns()
    settings_repository = settings or FakeSettings()
    transaction_boundary = SnapshotTransactions(
        conversation_repository,
        state_repository,
    )
    fixed_clock = clock or FixedClock()
    fixed_ids = ids or FixedIds(identifier(999))
    service = PrepareApplicationShellService(
        projects=project_repository,
        conversations=conversation_repository,
        conversation_states=state_repository,
        processing_runs=run_repository,
        settings=settings_repository,
        transactions=transaction_boundary,
        clock=fixed_clock,
        id_generator=fixed_ids,
    )
    return (
        service,
        project_repository,
        conversation_repository,
        state_repository,
        run_repository,
        settings_repository,
        transaction_boundary,
        fixed_clock,
        fixed_ids,
    )


def test_recovery_preflight_is_first_and_short_circuits_conversation_setup() -> None:
    active = ProcessingRun(
        identifier(1),
        identifier(2),
        identifier(3),
        str(identifier(4)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fingerprint",
        NOW,
        None,
    )
    built = build_service(runs=FakeRuns(active))

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == RecoveryRequiredResult(active.id, active.conversation_id)
    assert built[4].calls == 1
    assert built[5].get_calls == 0
    assert built[2].get_calls == []
    assert built[2].list_calls == []
    assert built[6].entries == 0
    assert built[7].calls == 0
    assert built[8].calls == 0


def test_preferred_conversation_wins_without_mutating_its_setting() -> None:
    preferred = conversation(10, updated_at=NOW)
    latest = conversation(11, updated_at=NOW + timedelta(minutes=1))
    settings = FakeSettings(str(preferred.id), present=True)
    built = build_service(
        conversations=FakeConversations(preferred, latest),
        states=FakeStates(state(preferred.id), state(latest.id)),
        settings=settings,
    )

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == ShellReadyResult(preferred.id, False)
    assert built[3].get_calls == [preferred.id]
    assert built[2].list_calls == []
    assert settings.set_calls == 0


def test_stale_preference_falls_back_to_latest_then_uuid_ascending() -> None:
    active_project = Project(
        identifier(20),
        "Active",
        None,
        ProjectStatus.ACTIVE,
        NOW,
        NOW,
    )
    archived_project = Project(
        identifier(21),
        "Archived",
        None,
        ProjectStatus.ARCHIVED,
        NOW,
        NOW,
    )
    older = conversation(30, updated_at=NOW)
    later_uuid = conversation(
        32,
        project_id=active_project.id,
        updated_at=NOW + timedelta(minutes=2),
    )
    earlier_uuid = conversation(
        31,
        project_id=archived_project.id,
        updated_at=NOW + timedelta(minutes=2),
    )
    built = build_service(
        projects=FakeProjects(active_project, archived_project),
        conversations=FakeConversations(older, later_uuid, earlier_uuid),
        states=FakeStates(
            state(older.id),
            state(later_uuid.id),
            state(earlier_uuid.id),
        ),
        settings=FakeSettings(str(identifier(404)), present=True),
    )

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == ShellReadyResult(earlier_uuid.id, False)
    assert built[1].list_calls == [ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED]
    assert built[2].list_calls == [None, active_project.id, archived_project.id]
    assert built[3].get_calls == [earlier_uuid.id]


def test_missing_state_or_invalid_preference_returns_closed_setup_failure() -> None:
    selected = conversation(40)
    missing_state = build_service(
        conversations=FakeConversations(selected),
        settings=FakeSettings(str(selected.id), present=True),
    )[0].execute(PrepareApplicationShellRequest())
    invalid_setting = build_service(
        settings=FakeSettings("not-a-uuid", present=True)
    )[0].execute(PrepareApplicationShellRequest())

    assert missing_state == ShellPreparationFailureResult(
        ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
    )
    assert invalid_setting == missing_state


def test_first_run_atomically_creates_only_default_conversation_and_state() -> None:
    built = build_service()

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == ShellReadyResult(identifier(999), True)
    assert built[6].entries == 1
    assert built[7].calls == 1
    assert built[8].calls == 1
    assert tuple(built[2].records.values()) == (
        Conversation(identifier(999), None, None, NOW, NOW),
    )
    assert tuple(built[3].records.values()) == (state(identifier(999)),)
    assert built[5].set_calls == 0


def test_first_run_write_failure_rolls_back_and_returns_closed_setup_failure() -> None:
    states = FakeStates()
    states.fail_add = True
    built = build_service(states=states)

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == ShellPreparationFailureResult(
        ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
    )
    assert built[2].records == {}
    assert built[3].records == {}


def test_preflight_read_failure_has_its_distinct_closed_projection() -> None:
    runs = FakeRuns()
    runs.fail = True
    built = build_service(runs=runs)

    result = built[0].execute(PrepareApplicationShellRequest())

    assert result == ShellPreparationFailureResult(
        ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
    )
    assert built[5].get_calls == 0
    assert built[2].list_calls == []
