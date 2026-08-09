"""Focused TASK-0017 safe project adapter tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from context_for_ai.application.contracts import (
    ArchiveProjectPresentationRequest,
    InspectProjectsRequest,
    ProjectArchiveBlockedResult,
    ProjectArchiveSucceededResult,
    ProjectInspectionReadyResult,
    ProjectMutationRejectedResult,
    ProjectSelectionChangedResult,
    ProjectSelectionUnchangedResult,
    SelectProjectPresentationRequest,
)
from context_for_ai.application.conversation_state import (
    ArchiveProjectService,
    SelectProjectService,
)
from context_for_ai.application.manual_projects import (
    ArchiveProjectForPresentationService,
    InspectProjectsService,
    SelectProjectForPresentationService,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Project
from context_for_ai.domain.enums import ProjectStatus
from context_for_ai.domain.value_objects import DomainId


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"72000000-0000-4000-8000-{number:012d}")


class _Projects:
    def __init__(self, *projects: Project) -> None:
        self.values = {project.id: project for project in projects}

    def get(self, project_id: DomainId) -> Project | None:
        return self.values.get(project_id)

    def list_by_status(self, status: ProjectStatus) -> tuple[Project, ...]:
        return tuple(
            sorted(
                (item for item in self.values.values() if item.status is status),
                key=lambda item: (item.created_at, str(item.id)),
            )
        )

    def update(self, project: Project) -> None:
        self.values[project.id] = project


class _Conversations:
    def __init__(self, *conversations: Conversation) -> None:
        self.values = {item.id: item for item in conversations}

    def get(self, conversation_id: DomainId) -> Conversation | None:
        return self.values.get(conversation_id)

    def update(self, conversation: Conversation) -> None:
        self.values[conversation.id] = conversation

    def list_for_project(self, project_id):  # type: ignore[no-untyped-def]
        return tuple(item for item in self.values.values() if item.project_id == project_id)


class _States:
    def __init__(self, state: ConversationState) -> None:
        self.state = state
        self.cas_calls = 0

    def get(self, conversation_id: DomainId) -> ConversationState | None:
        return self.state if self.state.conversation_id == conversation_id else None

    def compare_and_swap(self, *, expected_version: int, state: ConversationState) -> bool:
        self.cas_calls += 1
        if self.state.version != expected_version:
            return False
        self.state = state
        return True


class _Runs:
    def __init__(self) -> None:
        self.active = None

    def get_non_terminal(self):  # type: ignore[no-untyped-def]
        return self.active


class _Boundary:
    def __init__(self) -> None:
        self.entries = 0

    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        self.entries += 1
        yield

    @contextmanager
    def snapshot(self):  # type: ignore[no-untyped-def]
        self.entries += 1
        yield


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW + timedelta(minutes=self.calls)


def _fixture():  # type: ignore[no-untyped-def]
    alpha = Project(identifier(1), "Alpha", None, ProjectStatus.ACTIVE, NOW, NOW)
    beta = Project(
        identifier(2),
        "Beta",
        "Archived work",
        ProjectStatus.ARCHIVED,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1),
    )
    conversation = Conversation(identifier(3), alpha.id, "Main", NOW, NOW)
    state = ConversationState(
        conversation.id,
        None,
        None,
        None,
        None,
        (),
        4,
        NOW,
    )
    projects = _Projects(alpha, beta)
    conversations = _Conversations(conversation)
    states = _States(state)
    runs = _Runs()
    boundary = _Boundary()
    clock = _Clock()
    select_raw = SelectProjectService(
        projects=projects,
        conversations=conversations,
        states=states,
        clock=clock,
        transactions=boundary,
    )
    archive_raw = ArchiveProjectService(
        projects=projects,
        conversations=conversations,
        processing_runs=runs,
        clock=clock,
        transactions=boundary,
    )
    return SimpleNamespace(
        alpha=alpha,
        beta=beta,
        conversation=conversation,
        projects=projects,
        conversations=conversations,
        states=states,
        runs=runs,
        boundary=boundary,
        clock=clock,
        inspect=InspectProjectsService(
            projects=projects,
            conversations=conversations,
            states=states,
            processing_runs=runs,
            snapshots=boundary,
        ),
        select=SelectProjectForPresentationService(
            select_project=select_raw,
            projects=projects,
            conversations=conversations,
            transactions=boundary,
        ),
        archive=ArchiveProjectForPresentationService(
            archive_project=archive_raw,
            projects=projects,
            conversations=conversations,
            processing_runs=runs,
            transactions=boundary,
        ),
    )


def test_project_inspection_projects_lists_association_and_active_run_guard() -> None:
    fixture = _fixture()
    fixture.runs.active = SimpleNamespace(conversation_id=fixture.conversation.id)

    result = fixture.inspect.execute(InspectProjectsRequest(fixture.conversation.id))

    assert isinstance(result, ProjectInspectionReadyResult)
    assert tuple(item.name for item in result.view.active_projects) == ("Alpha",)
    assert tuple(item.name for item in result.view.archived_projects) == ("Beta",)
    assert result.view.current_association.display_text == "Alpha"
    assert result.view.active_projects[0].archive_eligible is False
    assert result.view.active_projects[0].archive_ineligible_text == (
        "This project cannot be archived while it has an active request."
    )
    assert result.view.conversation_state_version == 4
    assert fixture.boundary.entries == 1
    assert str(fixture.alpha.id) not in repr(result)


def test_project_selection_changes_once_then_same_selection_is_unchanged() -> None:
    fixture = _fixture()

    changed = fixture.select.execute(
        SelectProjectPresentationRequest(
            fixture.conversation.id,
            None,
            4,
        )
    )

    assert isinstance(changed, ProjectSelectionChangedResult)
    assert changed.current_association is None
    assert changed.conversation_state_version == 5
    assert fixture.states.cas_calls == 1
    assert fixture.clock.calls == 1

    unchanged = fixture.select.execute(
        SelectProjectPresentationRequest(
            fixture.conversation.id,
            None,
            5,
        )
    )

    assert isinstance(unchanged, ProjectSelectionUnchangedResult)
    assert unchanged.conversation_state_version == 5
    assert fixture.states.cas_calls == 1
    assert fixture.clock.calls == 1


def test_archived_project_selection_is_rejected_without_state_write() -> None:
    fixture = _fixture()

    result = fixture.select.execute(
        SelectProjectPresentationRequest(
            fixture.conversation.id,
            fixture.beta.id,
            4,
        )
    )

    assert isinstance(result, ProjectMutationRejectedResult)
    assert result.safe_message == "Archived projects cannot be selected."
    assert fixture.states.cas_calls == 0
    assert fixture.clock.calls == 0


def test_archive_blocks_active_request_then_preserves_current_association() -> None:
    fixture = _fixture()
    fixture.runs.active = SimpleNamespace(conversation_id=fixture.conversation.id)

    blocked = fixture.archive.execute(
        ArchiveProjectPresentationRequest(fixture.alpha.id, True)
    )

    assert isinstance(blocked, ProjectArchiveBlockedResult)
    assert fixture.projects.get(fixture.alpha.id).status is ProjectStatus.ACTIVE
    fixture.runs.active = None

    archived = fixture.archive.execute(
        ArchiveProjectPresentationRequest(fixture.alpha.id, True)
    )

    assert isinstance(archived, ProjectArchiveSucceededResult)
    assert archived.archived_project.status.display_label == "Archived"
    assert archived.archived_project.is_current_association is True
    assert fixture.conversations.get(fixture.conversation.id).project_id == fixture.alpha.id
