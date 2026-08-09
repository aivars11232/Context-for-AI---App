"""Safe TASK-0017 project inspection, selection, and archive adapters."""

from __future__ import annotations

from context_for_ai.application.contracts import (
    ArchiveProject,
    ArchiveProjectInput,
    ArchiveProjectPresentationRequest,
    CanonicalLabelView,
    InspectProjectsRequest,
    InspectProjectsResult,
    ProjectArchiveBlockedResult,
    ProjectArchiveSucceededResult,
    ProjectAssociationView,
    ProjectInspectionEmptyResult,
    ProjectInspectionLoadFailureResult,
    ProjectInspectionReadyResult,
    ProjectInspectionView,
    ProjectItemView,
    ProjectMutationFailureResult,
    ProjectMutationRejectedResult,
    ProjectMutationResult,
    ProjectMutationStaleResult,
    ProjectSelectionChangedResult,
    ProjectSelectionUnchangedResult,
    SelectProject,
    SelectProjectInput,
    SelectProjectPresentationRequest,
)
from context_for_ai.application.manual_settings import ReadOnlySnapshotBoundary
from context_for_ai.domain.entities import Conversation, Project
from context_for_ai.domain.enums import ProjectStatus
from context_for_ai.domain.errors import DomainError, LifecycleInvariantError
from context_for_ai.domain.ports.errors import (
    ConcurrencyConflictError,
    PersistenceError,
)
from context_for_ai.domain.ports.repositories import (
    ConversationRepository,
    ConversationStateRepository,
    ProcessingRunRepository,
    ProjectRepository,
)
from context_for_ai.domain.ports.system import TransactionBoundary
from context_for_ai.domain.value_objects import DomainId, ensure_utc


def _label(status: ProjectStatus) -> CanonicalLabelView:
    rendered = status.value.lower().capitalize()
    return CanonicalLabelView(status.value, rendered)


def _utc_text(value: object) -> str:
    return ensure_utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")  # type: ignore[arg-type]


def _association(project: Project | None) -> ProjectAssociationView | None:
    if project is None:
        return None
    return ProjectAssociationView(
        name=project.name,
        status=_label(project.status),
        display_text=(
            project.name
            if project.status is ProjectStatus.ACTIVE
            else f"{project.name} — Archived (current association)"
        ),
    )


def _required_conversation(
    conversations: ConversationRepository,
    conversation_id: DomainId,
) -> Conversation:
    conversation = conversations.get(conversation_id)
    if conversation is None:
        raise PersistenceError("Project conversation is unavailable.")
    return conversation


def _active_run_project_id(
    *,
    processing_runs: ProcessingRunRepository,
    conversations: ConversationRepository,
) -> DomainId | None:
    run = processing_runs.get_non_terminal()
    if run is None:
        return None
    conversation = _required_conversation(conversations, run.conversation_id)
    return conversation.project_id


def _item(
    project: Project,
    *,
    ordinal: int,
    current_project_id: DomainId | None,
    active_run_project_id: DomainId | None,
) -> ProjectItemView:
    archive_eligible = (
        project.status is ProjectStatus.ACTIVE
        and project.id != active_run_project_id
    )
    return ProjectItemView(
        ordinal=ordinal,
        name=project.name,
        description=(
            "No description." if project.description is None else project.description
        ),
        status=_label(project.status),
        created_at_text=_utc_text(project.created_at),
        updated_at_text=_utc_text(project.updated_at),
        is_current_association=project.id == current_project_id,
        archive_eligible=archive_eligible,
        archive_ineligible_text=(
            ""
            if archive_eligible or project.status is ProjectStatus.ARCHIVED
            else "This project cannot be archived while it has an active request."
        ),
        private_project_id=project.id,
    )


class InspectProjectsService:
    """Read the conversation, state, projects, and archive guard in one snapshot."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        states: ConversationStateRepository,
        processing_runs: ProcessingRunRepository,
        snapshots: ReadOnlySnapshotBoundary,
    ) -> None:
        self._projects = projects
        self._conversations = conversations
        self._states = states
        self._processing_runs = processing_runs
        self._snapshots = snapshots

    def execute(self, request: InspectProjectsRequest) -> InspectProjectsResult:
        if not isinstance(request, InspectProjectsRequest):
            raise TypeError("InspectProjectsService requires its request type.")
        try:
            with self._snapshots.snapshot():
                conversation = _required_conversation(
                    self._conversations,
                    request.conversation_id,
                )
                state = self._states.get(request.conversation_id)
                if state is None or state.conversation_id != conversation.id:
                    raise PersistenceError("Project conversation state is unavailable.")
                active = self._projects.list_by_status(ProjectStatus.ACTIVE)
                archived = self._projects.list_by_status(ProjectStatus.ARCHIVED)
                current_project = (
                    None
                    if conversation.project_id is None
                    else self._projects.get(conversation.project_id)
                )
                if conversation.project_id is not None and current_project is None:
                    raise PersistenceError("Current project association is unavailable.")
                if not active and not archived and current_project is None:
                    return ProjectInspectionEmptyResult()
                guarded_project_id = _active_run_project_id(
                    processing_runs=self._processing_runs,
                    conversations=self._conversations,
                )
                active_items = tuple(
                    _item(
                        project,
                        ordinal=index,
                        current_project_id=conversation.project_id,
                        active_run_project_id=guarded_project_id,
                    )
                    for index, project in enumerate(active, start=1)
                )
                archived_items = tuple(
                    _item(
                        project,
                        ordinal=index,
                        current_project_id=conversation.project_id,
                        active_run_project_id=guarded_project_id,
                    )
                    for index, project in enumerate(archived, start=1)
                )
                return ProjectInspectionReadyResult(
                    ProjectInspectionView(
                        active_projects=active_items,
                        archived_projects=archived_items,
                        current_association=_association(current_project),
                        conversation_state_version=state.version,
                    )
                )
        except (DomainError, PersistenceError, KeyError, TypeError, ValueError):
            return ProjectInspectionLoadFailureResult()


class SelectProjectForPresentationService:
    """Map the canonical bounded-CAS selection result to safe presentation data."""

    def __init__(
        self,
        *,
        select_project: SelectProject,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        transactions: TransactionBoundary,
    ) -> None:
        self._select_project = select_project
        self._projects = projects
        self._conversations = conversations
        self._transactions = transactions

    def execute(
        self,
        request: SelectProjectPresentationRequest,
    ) -> ProjectMutationResult:
        if not isinstance(request, SelectProjectPresentationRequest):
            raise TypeError(
                "SelectProjectForPresentationService requires its request type."
        )
        try:
            with self._transactions.transaction():
                before = _required_conversation(
                    self._conversations,
                    request.conversation_id,
                )
                if request.project_id is not None:
                    target = self._projects.get(request.project_id)
                    if target is not None and target.status is ProjectStatus.ARCHIVED:
                        return ProjectMutationRejectedResult(
                            "ARCHIVED_PROJECT_NOT_SELECTABLE"
                        )
                output = self._select_project.execute(
                    SelectProjectInput(
                        conversation_id=request.conversation_id,
                        project_id=request.project_id,
                        expected_state_version=request.expected_state_version,
                    )
                )
                current = (
                    None
                    if output.conversation.project_id is None
                    else self._projects.get(output.conversation.project_id)
                )
                if output.conversation.project_id is not None and current is None:
                    raise PersistenceError("Selected project is unavailable.")
                association = _association(current)
                if before.project_id == output.conversation.project_id:
                    return ProjectSelectionUnchangedResult(
                        association,
                        output.state.version,
                    )
                return ProjectSelectionChangedResult(
                    association,
                    output.state.version,
                )
        except ConcurrencyConflictError:
            return ProjectMutationStaleResult()
        except LifecycleInvariantError:
            if request.project_id is not None:
                target = self._projects.get(request.project_id)
                if target is not None and target.status is ProjectStatus.ARCHIVED:
                    return ProjectMutationRejectedResult(
                        "ARCHIVED_PROJECT_NOT_SELECTABLE"
                    )
            return ProjectMutationFailureResult("PROJECT_SELECTION_FAILED")
        except (DomainError, PersistenceError, KeyError, TypeError, ValueError):
            return ProjectMutationFailureResult("PROJECT_SELECTION_FAILED")


class ArchiveProjectForPresentationService:
    """Map canonical archive guard and lifecycle outcomes to closed safe values."""

    def __init__(
        self,
        *,
        archive_project: ArchiveProject,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        processing_runs: ProcessingRunRepository,
        transactions: TransactionBoundary,
    ) -> None:
        self._archive_project = archive_project
        self._projects = projects
        self._conversations = conversations
        self._processing_runs = processing_runs
        self._transactions = transactions

    def execute(
        self,
        request: ArchiveProjectPresentationRequest,
    ) -> ProjectMutationResult:
        if not isinstance(request, ArchiveProjectPresentationRequest):
            raise TypeError(
                "ArchiveProjectForPresentationService requires its request type."
        )
        try:
            with self._transactions.transaction():
                project = self._projects.get(request.project_id)
                if project is None or project.status is not ProjectStatus.ACTIVE:
                    return ProjectMutationRejectedResult("PROJECT_NOT_ARCHIVABLE")
                if (
                    _active_run_project_id(
                        processing_runs=self._processing_runs,
                        conversations=self._conversations,
                    )
                    == project.id
                ):
                    return ProjectArchiveBlockedResult()
                output = self._archive_project.execute(
                    ArchiveProjectInput(request.project_id)
                )
                archived = self._projects.list_by_status(ProjectStatus.ARCHIVED)
                ordinal = next(
                    (
                        index
                        for index, candidate in enumerate(archived, start=1)
                        if candidate.id == output.project.id
                    ),
                    None,
                )
                if ordinal is None:
                    raise PersistenceError("Archived project is unavailable.")
                return ProjectArchiveSucceededResult(
                    _item(
                        output.project,
                        ordinal=ordinal,
                        current_project_id=(
                            output.project.id
                            if request.is_current_association
                            else None
                        ),
                        active_run_project_id=None,
                    )
                )
        except LifecycleInvariantError:
            try:
                guarded = _active_run_project_id(
                    processing_runs=self._processing_runs,
                    conversations=self._conversations,
                )
            except (DomainError, PersistenceError):
                guarded = None
            if guarded == request.project_id:
                return ProjectArchiveBlockedResult()
            return ProjectMutationRejectedResult("PROJECT_NOT_ARCHIVABLE")
        except (DomainError, PersistenceError, KeyError, TypeError, ValueError):
            return ProjectMutationFailureResult("PROJECT_ARCHIVE_FAILED")


__all__ = [
    "ArchiveProjectForPresentationService",
    "InspectProjectsService",
    "SelectProjectForPresentationService",
]
