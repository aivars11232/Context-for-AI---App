"""One finite TASK-0017 manual-operations worker and GUI-owned controller."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QThread,
    Qt,
    Signal,
    Slot,
)

from context_for_ai.application.contracts import (
    ArchiveProjectPresentationRequest,
    CreateMemoryPresentationRequest,
    DomainId,
    EditMemoryPresentationRequest,
    InspectManualSettingsRequest,
    InspectMemoriesRequest,
    InspectProjectsRequest,
    InspectValidationHistoryRequest,
    ManualSettingKey,
    ManualSettingsLoadFailureResult,
    ManualSettingsMutationFailureResult,
    ManualSettingsReadyResult,
    ManualSettingsUpdateSucceededResult,
    ManualSettingsValidationFailureResult,
    MemoryDuplicateDecision,
    MemoryDuplicateGuidanceResult,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryInspectionEmptyResult,
    MemoryInspectionItemView,
    MemoryInspectionLoadFailureResult,
    MemoryInspectionReadyResult,
    MemoryMutationFailureResult,
    MemoryMutationOperation,
    MemoryMutationRejectedResult,
    MemoryMutationStaleResult,
    MemoryMutationSucceededResult,
    MemoryMutationValidationFailureResult,
    ProjectArchiveBlockedResult,
    ProjectArchiveSucceededResult,
    ProjectInspectionEmptyResult,
    ProjectInspectionLoadFailureResult,
    ProjectInspectionReadyResult,
    ProjectItemView,
    ProjectMutationFailureResult,
    ProjectMutationRejectedResult,
    ProjectMutationStaleResult,
    ProjectSelectionChangedResult,
    ProjectSelectionUnchangedResult,
    SelectProjectPresentationRequest,
    SettingUpdate,
    SoftDeleteMemoryPresentationRequest,
    UiTheme,
    UpdateManualSettingsRequest,
    ValidationHistoryEmptyResult,
    ValidationHistoryLoadFailureResult,
    ValidationHistoryReadyResult,
)
from context_for_ai.ui.presentation import (
    ManualOperationKind,
    ManualOperationsExecutionFailureView,
    ManualOperationsTerminalEnvelope,
    MemoryPageState,
    ProjectsPageState,
    Route,
    SettingsApplyFailureView,
    SettingsPageState,
    ValidationHistoryPageState,
    contained_manual_operations_result,
)


def _role(offset: int) -> int:
    return int(Qt.ItemDataRole.UserRole) + offset


@dataclass(frozen=True, slots=True)
class ManualListRow:
    accessible_id: str
    accessible_name: str
    primary_text: str
    secondary_text: str = ""
    detail_text: str = ""
    enabled: bool = True
    current: bool = False


class ManualListModel(QAbstractListModel):
    """Replaceable primitive-only model shared by TASK-0017 pages."""

    _ACCESSIBLE_ID = _role(1)
    _ACCESSIBLE_NAME = _role(2)
    _PRIMARY_TEXT = _role(3)
    _SECONDARY_TEXT = _role(4)
    _DETAIL_TEXT = _role(5)
    _ENABLED = _role(6)
    _CURRENT = _role(7)
    _ROLES = {
        _ACCESSIBLE_ID: QByteArray(b"accessibleId"),
        _ACCESSIBLE_NAME: QByteArray(b"accessibleName"),
        _PRIMARY_TEXT: QByteArray(b"primaryText"),
        _SECONDARY_TEXT: QByteArray(b"secondaryText"),
        _DETAIL_TEXT: QByteArray(b"detailText"),
        _ENABLED: QByteArray(b"actionEnabled"),
        _CURRENT: QByteArray(b"current"),
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: tuple[ManualListRow, ...] = ()

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self,
        index: QModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        return {
            self._ACCESSIBLE_ID: row.accessible_id,
            self._ACCESSIBLE_NAME: row.accessible_name,
            self._PRIMARY_TEXT: row.primary_text,
            self._SECONDARY_TEXT: row.secondary_text,
            self._DETAIL_TEXT: row.detail_text,
            self._ENABLED: row.enabled,
            self._CURRENT: row.current,
        }.get(role)

    def replace(self, rows: tuple[ManualListRow, ...]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()


_QUERY_KIND_BY_ROUTE = {
    Route.MEMORY: ManualOperationKind.INSPECT_MEMORIES,
    Route.PROJECTS: ManualOperationKind.INSPECT_PROJECTS,
    Route.VALIDATION_HISTORY: ManualOperationKind.INSPECT_VALIDATION_HISTORY,
    Route.SETTINGS: ManualOperationKind.INSPECT_MANUAL_SETTINGS,
}


class ManualOperationsWorker(QObject):
    """Open, invoke, close, and emit exactly one manual-operation scope."""

    terminal = Signal(object)
    work_complete = Signal()

    def __init__(
        self,
        *,
        operation_id: int,
        generation: int,
        route: Route,
        conversation_id: DomainId,
        operation_kind: ManualOperationKind,
        request: object,
        scope_factory: object,
    ) -> None:
        super().__init__()
        self._operation_id = operation_id
        self._generation = generation
        self._route = route
        self._conversation_id = conversation_id
        self._operation_kind = operation_kind
        self._request = request
        self._scope_factory = scope_factory

    @Slot()
    def run(self) -> None:
        result: object = ManualOperationsExecutionFailureView(self._operation_kind)
        scope: Any | None = None
        try:
            scope = self._scope_factory.open_manual_operations_scope()
            use_case = {
                ManualOperationKind.INSPECT_MEMORIES: scope.inspect_memories,
                ManualOperationKind.CREATE_MEMORY: scope.create_memory_with_guidance,
                ManualOperationKind.EDIT_MEMORY: scope.edit_memory_for_presentation,
                ManualOperationKind.SOFT_DELETE_MEMORY: (
                    scope.soft_delete_memory_for_presentation
                ),
                ManualOperationKind.INSPECT_PROJECTS: scope.inspect_projects,
                ManualOperationKind.SELECT_PROJECT: (
                    scope.select_project_for_presentation
                ),
                ManualOperationKind.ARCHIVE_PROJECT: (
                    scope.archive_project_for_presentation
                ),
                ManualOperationKind.INSPECT_VALIDATION_HISTORY: (
                    scope.inspect_validation_history
                ),
                ManualOperationKind.INSPECT_MANUAL_SETTINGS: (
                    scope.inspect_manual_settings
                ),
                ManualOperationKind.UPDATE_MANUAL_SETTINGS: (
                    scope.update_manual_settings
                ),
            }[self._operation_kind]
            result = use_case.execute(self._request)
        except BaseException:
            result = ManualOperationsExecutionFailureView(self._operation_kind)
        finally:
            if scope is not None:
                try:
                    scope.close()
                except BaseException:
                    result = ManualOperationsExecutionFailureView(
                        self._operation_kind
                    )
        self.terminal.emit(
            ManualOperationsTerminalEnvelope(
                operation_id=self._operation_id,
                generation=self._generation,
                route=self._route,
                conversation_id=self._conversation_id,
                operation_kind=self._operation_kind,
                result=contained_manual_operations_result(
                    self._operation_kind,
                    result,
                ),
            )
        )
        self.work_complete.emit()


@dataclass(slots=True)
class _ActiveManualOperation:
    operation_id: int
    generation: int
    route: Route
    conversation_id: DomainId
    operation_kind: ManualOperationKind
    mutation: bool
    refreshed: bool
    thread: QThread
    worker: ManualOperationsWorker
    terminal_consumed: bool = False
    thread_finished: bool = False


class ManualOperationsController:
    """GUI-owned TASK-0017 route state with one finite worker at a time."""

    def __init__(
        self,
        *,
        owner: Any,
        scope_factory: object,
        theme_applier: Callable[[UiTheme], None],
    ) -> None:
        self._owner = owner
        self._scope_factory = scope_factory
        self._theme_applier = theme_applier
        self._conversation_id: DomainId | None = None
        self._route = Route.CHAT
        self._generation = 0
        self._next_operation_id = 1
        self._active: _ActiveManualOperation | None = None
        self._pending_read_route: Route | None = None
        self._disposed = False
        self._dirty = {route: True for route in _QUERY_KIND_BY_ROUTE}
        self._loaded = {route: False for route in _QUERY_KIND_BY_ROUTE}

        self.memory_state = MemoryPageState.INACTIVE
        self.projects_state = ProjectsPageState.INACTIVE
        self.validation_state = ValidationHistoryPageState.INACTIVE
        self.settings_state = SettingsPageState.INACTIVE
        self.memory_status = ""
        self.projects_status = ""
        self.validation_status = ""
        self.settings_status = ""
        self.memory_announcement = ""
        self.projects_announcement = ""
        self.validation_announcement = ""
        self.settings_announcement = ""
        self.memory_announcement_revision = 0
        self.projects_announcement_revision = 0
        self.validation_announcement_revision = 0
        self.settings_announcement_revision = 0

        self.memory_items = ManualListModel(owner)
        self.memory_details = ManualListModel(owner)
        self.memory_sources = ManualListModel(owner)
        self.memory_revisions = ManualListModel(owner)
        self.memory_duplicates = ManualListModel(owner)
        self.memory_errors = ManualListModel(owner)
        self.active_projects = ManualListModel(owner)
        self.archived_projects = ManualListModel(owner)
        self.validation_attempts = ManualListModel(owner)
        self.validation_corrections = ManualListModel(owner)
        self.validation_summary = ManualListModel(owner)
        self.configuration_fields = ManualListModel(owner)
        self.settings_errors = ManualListModel(owner)

        self._memory_views: tuple[MemoryInspectionItemView, ...] = ()
        self._selected_memory_index: int | None = None
        self._memory_filter = MemoryStatus.ACTIVE
        self._memory_editor_mode = ""
        self._memory_editor_request: CreateMemoryPresentationRequest | None = None
        self.memory_editor_type = MemoryType.PROJECT_FACT.value
        self.memory_editor_scope = MemoryScope.CONVERSATION.value
        self.memory_editor_content = ""
        self.memory_editor_keywords = ""
        self.memory_editor_topics = ""
        self.memory_editor_importance = "0.5"
        self.memory_editor_confidence = "0.5"
        self.memory_editor_expiry = ""
        self._active_project_views: tuple[ProjectItemView, ...] = ()
        self._archived_project_views: tuple[ProjectItemView, ...] = ()
        self._project_state_version = 0
        self._archive_target: ProjectItemView | None = None
        self._theme = UiTheme.SYSTEM
        self._pending_theme = UiTheme.SYSTEM
        self._context_visible = True
        self._pending_context_visible = True
        self.configuration_fingerprint = ""

    @property
    def active_operation_id(self) -> int | None:
        return None if self._active is None else self._active.operation_id

    @property
    def pending_read_route(self) -> Route | None:
        return self._pending_read_route

    @property
    def memory_filter(self) -> str:
        return self._memory_filter.value

    @property
    def memory_editor_mode(self) -> str:
        return self._memory_editor_mode

    @property
    def selected_memory_index(self) -> int:
        return -1 if self._selected_memory_index is None else self._selected_memory_index

    @property
    def theme(self) -> str:
        return self._theme.value

    @property
    def pending_theme(self) -> str:
        return self._pending_theme.value

    @property
    def context_panel_visible(self) -> bool:
        return self._context_visible

    @property
    def pending_context_panel_visible(self) -> bool:
        return self._pending_context_visible

    @property
    def settings_save_enabled(self) -> bool:
        return bool(
            self.settings_state
            in {SettingsPageState.READY, SettingsPageState.VALIDATION_ERROR}
            and self._active is None
            and (
                self._pending_theme is not self._theme
                or self._pending_context_visible != self._context_visible
            )
        )

    def _notify(self) -> None:
        self._owner.changed.emit()

    def _announce(self, route: Route, text: str) -> None:
        if route is Route.MEMORY:
            self.memory_announcement = text
            self.memory_announcement_revision += 1
            revision = self.memory_announcement_revision
        elif route is Route.PROJECTS:
            self.projects_announcement = text
            self.projects_announcement_revision += 1
            revision = self.projects_announcement_revision
        elif route is Route.VALIDATION_HISTORY:
            self.validation_announcement = text
            self.validation_announcement_revision += 1
            revision = self.validation_announcement_revision
        else:
            self.settings_announcement = text
            self.settings_announcement_revision += 1
            revision = self.settings_announcement_revision
        self._owner._manual_announcement(route, text, revision)

    def set_initial_conversation(self, conversation_id: DomainId) -> None:
        if self._conversation_id is not None or self._disposed:
            raise RuntimeError("Initial manual-operation conversation may be set once.")
        self._conversation_id = conversation_id

    def set_initial_preferences(
        self,
        *,
        theme: UiTheme,
        context_panel_visible: bool,
    ) -> None:
        self._theme = theme
        self._pending_theme = theme
        self._context_visible = context_panel_visible
        self._pending_context_visible = context_panel_visible

    def navigate_away(self, route: Route) -> None:
        self._route = route
        self._generation += 1
        self._pending_read_route = None
        self._deactivate_pages()
        self._notify()

    def navigate(self, route: Route) -> bool:
        if (
            self._disposed
            or self._conversation_id is None
            or route not in _QUERY_KIND_BY_ROUTE
            or self._shutdown_state()
        ):
            return False
        refreshed = self._route is route
        self._route = route
        self._deactivate_pages(except_route=route)
        self._request_read(route, refreshed=refreshed)
        return True

    def refresh(self, route: Route) -> bool:
        if self._disposed or self._route is not route or self._conversation_id is None:
            return False
        self._request_read(route, refreshed=True)
        return True

    def _deactivate_pages(self, except_route: Route | None = None) -> None:
        if except_route is not Route.MEMORY:
            self.memory_state = MemoryPageState.INACTIVE
            self.memory_status = ""
            self._clear_memory()
        if except_route is not Route.PROJECTS:
            self.projects_state = ProjectsPageState.INACTIVE
            self.projects_status = ""
            self._clear_projects()
        if except_route is not Route.VALIDATION_HISTORY:
            self.validation_state = ValidationHistoryPageState.INACTIVE
            self.validation_status = ""
            self.validation_attempts.replace(())
            self.validation_corrections.replace(())
        if except_route is not Route.SETTINGS:
            self.settings_state = SettingsPageState.INACTIVE
            self.settings_status = ""
            self.configuration_fields.replace(())
            self.settings_errors.replace(())

    def _request_read(self, route: Route, *, refreshed: bool) -> None:
        self._generation += 1
        request = self._query_request(route)
        self._set_loading(route)
        if self._active is None:
            self._start(
                route=route,
                kind=_QUERY_KIND_BY_ROUTE[route],
                request=request,
                mutation=False,
                refreshed=refreshed,
            )
        else:
            self._pending_read_route = route
        self._notify()

    def _query_request(self, route: Route) -> object:
        conversation_id = self._conversation_id
        if conversation_id is None:
            raise RuntimeError("Manual query requires a conversation.")
        if route is Route.MEMORY:
            selected_id = (
                None
                if self._selected_memory_index is None
                else self._memory_views[self._selected_memory_index].private_memory_id
            )
            return InspectMemoriesRequest(self._memory_filter, selected_id)
        if route is Route.PROJECTS:
            return InspectProjectsRequest(conversation_id)
        if route is Route.VALIDATION_HISTORY:
            return InspectValidationHistoryRequest(conversation_id)
        return InspectManualSettingsRequest()

    def _set_loading(self, route: Route) -> None:
        if route is Route.MEMORY:
            self.memory_state = MemoryPageState.LOADING
            self.memory_status = "Loading memories."
            self._clear_memory()
        elif route is Route.PROJECTS:
            self.projects_state = ProjectsPageState.LOADING
            self.projects_status = "Loading projects."
            self._clear_projects()
        elif route is Route.VALIDATION_HISTORY:
            self.validation_state = ValidationHistoryPageState.LOADING
            self.validation_status = "Loading validation history."
            self.validation_attempts.replace(())
            self.validation_corrections.replace(())
            self.validation_summary.replace(())
        else:
            self.settings_state = SettingsPageState.LOADING
            self.settings_status = "Loading settings."
            self.configuration_fields.replace(())
            self.settings_errors.replace(())
        self._announce(route, self._status(route))

    def _status(self, route: Route) -> str:
        return {
            Route.MEMORY: self.memory_status,
            Route.PROJECTS: self.projects_status,
            Route.VALIDATION_HISTORY: self.validation_status,
            Route.SETTINGS: self.settings_status,
        }[route]

    def _start(
        self,
        *,
        route: Route,
        kind: ManualOperationKind,
        request: object,
        mutation: bool,
        refreshed: bool = False,
    ) -> None:
        if self._active is not None or self._conversation_id is None or self._disposed:
            raise RuntimeError("Only one manual-operation worker may be owned.")
        operation_id = self._next_operation_id
        self._next_operation_id += 1
        thread = QThread(self._owner)
        thread.setObjectName(f"contextForAiManual{operation_id}")
        worker = ManualOperationsWorker(
            operation_id=operation_id,
            generation=self._generation,
            route=route,
            conversation_id=self._conversation_id,
            operation_kind=kind,
            request=request,
            scope_factory=self._scope_factory,
        )
        worker.moveToThread(thread)
        active = _ActiveManualOperation(
            operation_id,
            self._generation,
            route,
            self._conversation_id,
            kind,
            mutation,
            refreshed,
            thread,
            worker,
        )
        self._active = active
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.terminal.connect(
            self._owner._manual_terminal_received,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.work_complete.connect(worker.deleteLater)
        worker.work_complete.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(
            self._owner._manual_thread_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        thread.finished.connect(thread.deleteLater)
        try:
            thread.start()
        except BaseException:
            active.terminal_consumed = True
            active.thread_finished = True
            self._apply(
                active,
                ManualOperationsExecutionFailureView(kind),
            )
            self._release(active)

    def _start_mutation(
        self,
        route: Route,
        kind: ManualOperationKind,
        request: object,
        status: str,
    ) -> bool:
        if self._active is not None or self._disposed or self._route is not route:
            return False
        self._generation += 1
        if route is Route.MEMORY:
            self.memory_errors.replace(())
            self.memory_state = MemoryPageState.SAVING
            self.memory_status = status
        elif route is Route.PROJECTS:
            self.projects_state = ProjectsPageState.SAVING
            self.projects_status = status
        else:
            self.settings_state = SettingsPageState.SAVING
            self.settings_status = status
        self._announce(route, status)
        self._start(route=route, kind=kind, request=request, mutation=True)
        self._notify()
        return True

    def receive_terminal(self, envelope: object) -> None:
        if self._disposed or not isinstance(envelope, ManualOperationsTerminalEnvelope):
            return
        active = self._active
        if (
            active is None
            or active.terminal_consumed
            or envelope.operation_id != active.operation_id
            or envelope.operation_kind is not active.operation_kind
            or envelope.generation != active.generation
            or envelope.route is not active.route
            or envelope.conversation_id != active.conversation_id
        ):
            return
        active.terminal_consumed = True
        if active.mutation and not self._shutdown_state():
            result = self._apply_global_mutation(active, envelope.result)
        else:
            result = envelope.result
        if (
            not self._shutdown_state()
            and envelope.generation == self._generation
            and envelope.route is self._route
        ):
            self._apply(active, result)
        self._release(active)

    def receive_thread_finished(self, thread: object) -> None:
        active = self._active
        if self._disposed or active is None or thread is not active.thread:
            return
        if active.thread_finished:
            return
        active.thread_finished = True
        self._release(active)

    def _release(self, active: _ActiveManualOperation) -> None:
        if (
            self._active is not active
            or not active.terminal_consumed
            or not active.thread_finished
        ):
            return
        self._active = None
        pending = self._pending_read_route
        self._pending_read_route = None
        if (
            pending is not None
            and not self._disposed
            and self._route is pending
            and self._conversation_id is not None
            and not self._shutdown_state()
        ):
            self._request_read(pending, refreshed=True)
        self._notify()
        if self._shutdown_state():
            self._owner._owned_worker_released()

    def _apply(self, active: _ActiveManualOperation, result: object) -> None:
        if active.route is Route.MEMORY:
            self._apply_memory(active, result)
        elif active.route is Route.PROJECTS:
            self._apply_projects(active, result)
        elif active.route is Route.VALIDATION_HISTORY:
            self._apply_validation(active, result)
        else:
            self._apply_settings(active, result)
        self._notify()

    def _apply_global_mutation(
        self,
        active: _ActiveManualOperation,
        result: object,
    ) -> object:
        """Apply committed cross-page effects without publishing page content."""

        if isinstance(result, MemoryMutationSucceededResult):
            self._dirty[Route.MEMORY] = True
        elif isinstance(result, ProjectSelectionChangedResult):
            self._project_state_version = result.conversation_state_version
            self._dirty[Route.PROJECTS] = True
            self._dirty[Route.MEMORY] = True
            if active.conversation_id == self._conversation_id:
                self._owner._current_project_changed()
        elif isinstance(result, ProjectSelectionUnchangedResult):
            self._project_state_version = result.conversation_state_version
        elif isinstance(result, ProjectArchiveSucceededResult):
            self._dirty[Route.PROJECTS] = True
            self._dirty[Route.MEMORY] = True
            if (
                result.archived_project.is_current_association
                and active.conversation_id == self._conversation_id
            ):
                self._owner._current_project_changed()
        elif isinstance(result, ProjectMutationStaleResult):
            self._dirty[Route.PROJECTS] = True
        elif isinstance(result, ManualSettingsUpdateSucceededResult):
            try:
                self._theme_applier(result.effective_theme)
                self._owner._apply_context_panel_visible(
                    result.effective_context_panel_visible
                )
            except BaseException:
                return SettingsApplyFailureView()
            self._theme = result.effective_theme
            self._pending_theme = result.effective_theme
            self._context_visible = result.effective_context_panel_visible
            self._pending_context_visible = result.effective_context_panel_visible
        return result

    def _apply_memory(self, active: _ActiveManualOperation, result: object) -> None:
        if isinstance(result, MemoryInspectionReadyResult):
            self._memory_views = result.view.items
            self._selected_memory_index = (
                None
                if result.view.selected_ordinal is None
                else result.view.selected_ordinal - 1
            )
            self._replace_memory_rows()
            self.memory_state = MemoryPageState.READY
            self.memory_status = (
                "Memories refreshed." if active.refreshed else "Memories loaded."
            )
            self._loaded[Route.MEMORY] = True
            self._dirty[Route.MEMORY] = False
        elif isinstance(result, MemoryInspectionEmptyResult):
            self._clear_memory()
            self.memory_state = MemoryPageState.EMPTY
            self.memory_status = result.safe_message
        elif isinstance(result, (MemoryInspectionLoadFailureResult, ManualOperationsExecutionFailureView)) and not active.mutation:
            self._clear_memory()
            self.memory_state = MemoryPageState.LOAD_ERROR
            self.memory_status = result.safe_message
        elif isinstance(result, MemoryDuplicateGuidanceResult):
            self.memory_duplicates.replace(
                tuple(
                    ManualListRow(
                        f"memoryDuplicate-{item.ordinal}",
                        f"Possible duplicate {item.ordinal}: {item.effective_status.display_label}",
                        item.content,
                        item.owner_display_text,
                        item.updated_at_text,
                    )
                    for item in result.candidates
                )
            )
            self.memory_state = MemoryPageState.DUPLICATE_GUIDANCE
            self.memory_status = result.safe_message
        elif isinstance(result, MemoryMutationValidationFailureResult):
            self.memory_errors.replace(
                tuple(
                    ManualListRow(
                        f"memoryError-{index}",
                        error.safe_message,
                        error.field.value,
                        error.safe_message,
                    )
                    for index, error in enumerate(result.errors, start=1)
                )
            )
            self.memory_state = MemoryPageState.EDITING
            self.memory_status = result.safe_message
        elif isinstance(result, MemoryMutationSucceededResult):
            self._memory_filter = (
                MemoryStatus.DELETED
                if result.operation is MemoryMutationOperation.SOFT_DELETE
                else MemoryStatus.ACTIVE
            )
            self._memory_views = (result.affected,)
            self._selected_memory_index = 0
            self._replace_memory_rows()
            self.memory_state = MemoryPageState.READY
            self.memory_status = result.safe_message
            self._memory_editor_mode = ""
            self._memory_editor_request = None
            self.memory_errors.replace(())
            if self._route is Route.MEMORY:
                self._pending_read_route = Route.MEMORY
        elif isinstance(
            result,
            (
                MemoryMutationStaleResult,
                MemoryMutationRejectedResult,
                MemoryMutationFailureResult,
                ManualOperationsExecutionFailureView,
            ),
        ):
            self.memory_state = MemoryPageState.MUTATION_ERROR
            self.memory_status = result.safe_message
            if isinstance(result, MemoryMutationStaleResult):
                self._dirty[Route.MEMORY] = True
                self._memory_editor_mode = ""
                self._memory_editor_request = None
        else:
            self.memory_state = MemoryPageState.MUTATION_ERROR
            self.memory_status = "Memory could not be changed safely."
        self._announce(Route.MEMORY, self.memory_status)

    def _replace_memory_rows(self) -> None:
        self.memory_items.replace(
            tuple(
                ManualListRow(
                    f"memoryItem-{item.ordinal}",
                    (
                        f"Memory {item.ordinal}: {item.summary.type.display_label}, "
                        f"{item.summary.effective_status.display_label}"
                    ),
                    item.summary.content,
                    item.summary.owner.display_text,
                    (
                        f"{item.summary.scope.display_label} · "
                        f"{item.summary.updated_at_text}"
                    ),
                    current=index == self._selected_memory_index,
                )
                for index, item in enumerate(self._memory_views)
            )
        )
        self._replace_selected_memory_details()

    def _replace_selected_memory_details(self) -> None:
        if self._selected_memory_index is None:
            self.memory_details.replace(())
            self.memory_sources.replace(())
            self.memory_revisions.replace(())
            return
        selected = self._memory_views[self._selected_memory_index]
        summary = selected.summary
        details = selected.details
        keywords = "None recorded." if not details.keywords else "\n".join(details.keywords)
        topics = (
            "None recorded." if not details.topic_terms else "\n".join(details.topic_terms)
        )
        self.memory_details.replace(
            tuple(
                ManualListRow(
                    f"memoryDetail-{index}",
                    f"{label}: {value}",
                    label,
                    value,
                )
                for index, (label, value) in enumerate(
                    (
                        ("Type", summary.type.display_label),
                        ("Scope", summary.scope.display_label),
                        ("Owner", summary.owner.display_text),
                        ("Content", details.content),
                        ("Keywords", keywords),
                        ("Topic terms", topics),
                        ("Importance", details.importance.display_text),
                        ("Confidence", details.confidence.display_text),
                        ("Expiry", details.expires_at_text),
                        ("Stored status", details.stored_status.display_label),
                        ("Effective status", details.effective_status.display_label),
                        ("Evaluated at", details.evaluated_at_text),
                        ("Created", details.created_at_text),
                        ("Updated", details.updated_at_text),
                        ("Deleted", details.deleted_at_text),
                    ),
                    start=1,
                )
            )
        )
        self.memory_sources.replace(
            tuple(
                ManualListRow(
                    f"memorySource-{item.ordinal}",
                    f"Source {item.ordinal}: {item.kind.display_label}",
                    item.description,
                    item.source_message,
                    item.created_at_text,
                )
                for item in details.sources
            )
        )
        self.memory_revisions.replace(
            tuple(
                ManualListRow(
                    f"memoryRevision-{item.revision_number}",
                    f"Revision {item.revision_number}: {item.operation.display_label}",
                    item.content_snapshot,
                    item.stored_status.display_label,
                    item.performed_at_text,
                )
                for item in details.revisions
            )
        )

    def _clear_memory(self) -> None:
        self._memory_views = ()
        self._selected_memory_index = None
        self._memory_editor_mode = ""
        self._memory_editor_request = None
        self.memory_items.replace(())
        self.memory_details.replace(())
        self.memory_sources.replace(())
        self.memory_revisions.replace(())
        self.memory_duplicates.replace(())
        self.memory_errors.replace(())

    def _apply_projects(self, active: _ActiveManualOperation, result: object) -> None:
        if isinstance(result, ProjectInspectionReadyResult):
            self._active_project_views = result.view.active_projects
            self._archived_project_views = result.view.archived_projects
            self._project_state_version = result.view.conversation_state_version
            self._replace_project_rows()
            self.projects_state = ProjectsPageState.READY
            self.projects_status = (
                "Projects refreshed." if active.refreshed else "Projects loaded."
            )
            self._dirty[Route.PROJECTS] = False
        elif isinstance(result, ProjectInspectionEmptyResult):
            self._clear_projects()
            self.projects_state = ProjectsPageState.EMPTY
            self.projects_status = result.safe_message
        elif isinstance(result, (ProjectInspectionLoadFailureResult, ManualOperationsExecutionFailureView)) and not active.mutation:
            self._clear_projects()
            self.projects_state = ProjectsPageState.LOAD_ERROR
            self.projects_status = result.safe_message
        elif isinstance(result, ProjectSelectionChangedResult):
            self.projects_state = ProjectsPageState.READY
            self.projects_status = result.safe_message
            if self._route is Route.PROJECTS:
                self._pending_read_route = Route.PROJECTS
        elif isinstance(result, ProjectSelectionUnchangedResult):
            self.projects_state = ProjectsPageState.READY
            self.projects_status = result.safe_message
        elif isinstance(result, ProjectArchiveSucceededResult):
            self.projects_state = ProjectsPageState.READY
            self.projects_status = result.safe_message
            if self._route is Route.PROJECTS:
                self._pending_read_route = Route.PROJECTS
        elif isinstance(
            result,
            (
                ProjectArchiveBlockedResult,
                ProjectMutationStaleResult,
                ProjectMutationRejectedResult,
                ProjectMutationFailureResult,
                ManualOperationsExecutionFailureView,
            ),
        ):
            self.projects_state = ProjectsPageState.MUTATION_ERROR
            self.projects_status = result.safe_message
        self._archive_target = None
        if not isinstance(result, ProjectSelectionUnchangedResult):
            self._announce(Route.PROJECTS, self.projects_status)

    def _replace_project_rows(self) -> None:
        def rows(values: tuple[ProjectItemView, ...], active: bool) -> tuple[ManualListRow, ...]:
            prefix = "activeProject" if active else "archivedProject"
            label = "Active project" if active else "Archived project"
            return tuple(
                ManualListRow(
                    f"{prefix}-{item.ordinal}",
                    (
                        f"{label} {item.ordinal}: {item.name}"
                        + (", current association" if item.is_current_association else "")
                    ),
                    item.name,
                    item.description,
                    item.status.display_label,
                    enabled=(active and item.archive_eligible),
                    current=item.is_current_association,
                )
                for item in values
            )
        self.active_projects.replace(rows(self._active_project_views, True))
        self.archived_projects.replace(rows(self._archived_project_views, False))

    def _clear_projects(self) -> None:
        self._active_project_views = ()
        self._archived_project_views = ()
        self._archive_target = None
        self.active_projects.replace(())
        self.archived_projects.replace(())

    def _apply_validation(self, active: _ActiveManualOperation, result: object) -> None:
        if isinstance(result, ValidationHistoryReadyResult):
            terminal = result.view.terminal_status
            self.validation_summary.replace(
                tuple(
                    ManualListRow(
                        f"validationSummary-{index}",
                        f"{label}: {value}",
                        label,
                        value,
                    )
                    for index, (label, value) in enumerate(
                        (
                            ("Request", result.view.target.request_label),
                            ("Outcome", result.view.target.outcome_label),
                            (
                                "Processing checkpoint",
                                result.view.target.checkpoint_label,
                            ),
                            ("Correction count", str(result.view.correction_count)),
                            (
                                "Final status",
                                "Not recorded."
                                if terminal is None
                                else (
                                    f"{terminal.kind_label}: "
                                    f"{terminal.safe_message}"
                                ),
                            ),
                        ),
                        start=1,
                    )
                )
            )
            self.validation_attempts.replace(
                tuple(
                    ManualListRow(
                        f"validationAttempt-{item.attempt_number}",
                        (
                            f"Attempt {item.attempt_number}: "
                            f"{item.purpose.display_label}, {item.outcome.display_label}"
                        ),
                        item.display_identity,
                        (
                            f"Purpose: {item.purpose.display_label} · "
                            f"Attempt outcome: {item.outcome.display_label}"
                        ),
                        self._validation_attempt_details(item),
                    )
                    for item in result.view.attempts.items
                )
            )
            self.validation_corrections.replace(
                tuple(
                    ManualListRow(
                        f"validationCorrection-{item.correction_number}",
                        item.display_text,
                        item.display_text,
                    )
                    for item in result.view.corrections
                )
            )
            self.validation_state = ValidationHistoryPageState.READY
            self.validation_status = (
                "Validation history refreshed."
                if active.refreshed
                else "Validation history loaded."
            )
            self._dirty[Route.VALIDATION_HISTORY] = False
        elif isinstance(result, ValidationHistoryEmptyResult):
            self.validation_summary.replace(())
            self.validation_attempts.replace(())
            self.validation_corrections.replace(())
            self.validation_state = ValidationHistoryPageState.EMPTY
            self.validation_status = result.safe_message
        else:
            self.validation_summary.replace(())
            self.validation_attempts.replace(())
            self.validation_corrections.replace(())
            self.validation_state = ValidationHistoryPageState.LOAD_ERROR
            self.validation_status = (
                result.safe_message
                if isinstance(
                    result,
                    (ValidationHistoryLoadFailureResult, ManualOperationsExecutionFailureView),
                )
                else "Validation history could not be loaded safely."
            )
        self._announce(Route.VALIDATION_HISTORY, self.validation_status)

    @staticmethod
    def _validation_attempt_details(item: object) -> str:
        validation = getattr(item, "validation", None)
        failure = getattr(item, "safe_transport_failure", None)
        lines: list[str] = []
        display_text = getattr(item, "validation_display_text", "")
        if display_text:
            lines.append(display_text)
        if validation is not None:
            lines.extend(
                (
                    f"Validation status: {validation.status.display_label}",
                    f"Score: {validation.score.display_text}",
                )
            )
            lines.extend(
                f"Violation {violation.ordinal}: {violation.code.display_label}. "
                f"{violation.message}"
                for violation in validation.violations
            )
            lines.extend(
                (
                    f"Evidence {evidence.ordinal}: {evidence.check_id.display_label}, "
                    f"{evidence.severity.display_label}, "
                    f"{evidence.outcome.display_label}. {evidence.explanation}"
                )
                for evidence in validation.evidence
            )
        if failure is not None:
            lines.append(
                f"{failure.stage.display_label}: {failure.code.display_label}. "
                f"{failure.safe_message}"
            )
        correction = getattr(item, "correction_from_previous", None)
        if correction is not None:
            lines.append(f"Correction from attempt {correction}.")
        return "\n".join(lines)

    def _apply_settings(self, active: _ActiveManualOperation, result: object) -> None:
        if isinstance(result, ManualSettingsReadyResult):
            self._theme = result.view.theme
            self._pending_theme = result.view.theme
            self._context_visible = result.view.context_panel_visible
            self._pending_context_visible = result.view.context_panel_visible
            self.configuration_fingerprint = result.view.configuration.fingerprint
            rows: list[ManualListRow] = []
            for category in result.view.configuration.categories:
                for item in category.fields:
                    rows.append(
                        ManualListRow(
                            f"configurationField-{category.ordinal}-{item.ordinal}",
                            (
                                f"{item.label}: {item.value_text}. Origin: "
                                f"{item.origin.display_label}"
                            ),
                            item.label,
                            item.value_text,
                            item.origin.display_label,
                        )
                    )
            self.configuration_fields.replace(tuple(rows))
            self.settings_errors.replace(())
            self.settings_state = SettingsPageState.READY
            self.settings_status = (
                "Settings refreshed." if active.refreshed else "Settings loaded."
            )
            self._dirty[Route.SETTINGS] = False
        elif isinstance(result, ManualSettingsLoadFailureResult) or (
            isinstance(result, ManualOperationsExecutionFailureView) and not active.mutation
        ):
            self.configuration_fields.replace(())
            self.settings_state = SettingsPageState.LOAD_ERROR
            self.settings_status = result.safe_message
        elif isinstance(result, ManualSettingsValidationFailureResult):
            self.settings_errors.replace(
                tuple(
                    ManualListRow(
                        f"settingsError-{index}",
                        error.safe_message,
                        error.safe_message,
                    )
                    for index, error in enumerate(result.errors, start=1)
                )
            )
            self.settings_state = SettingsPageState.VALIDATION_ERROR
            self.settings_status = result.safe_message
        elif isinstance(result, ManualSettingsUpdateSucceededResult):
            self.settings_state = SettingsPageState.READY
            self.settings_status = result.safe_message
            self.settings_errors.replace(())
        elif isinstance(result, SettingsApplyFailureView):
            self.settings_state = SettingsPageState.MUTATION_ERROR
            self.settings_status = result.safe_message
        elif isinstance(result, (ManualSettingsMutationFailureResult, ManualOperationsExecutionFailureView)):
            self.settings_state = SettingsPageState.MUTATION_ERROR
            self.settings_status = result.safe_message
        self._announce(Route.SETTINGS, self.settings_status)

    def set_memory_filter(self, value: str) -> bool:
        if self._route is not Route.MEMORY or self._active is not None:
            return False
        try:
            selected = MemoryStatus(value)
        except ValueError:
            return False
        if selected is self._memory_filter:
            return False
        self._memory_filter = selected
        self._selected_memory_index = None
        self._request_read(Route.MEMORY, refreshed=True)
        return True

    def select_memory(self, row: int) -> bool:
        if (
            self._route is not Route.MEMORY
            or self.memory_state is not MemoryPageState.READY
            or not isinstance(row, int)
            or isinstance(row, bool)
            or row not in range(len(self._memory_views))
        ):
            return False
        self._selected_memory_index = row
        self._replace_memory_rows()
        self._notify()
        return True

    def begin_create_memory(self) -> bool:
        if (
            self._route is not Route.MEMORY
            or self._active is not None
            or self.memory_state not in {
                MemoryPageState.READY,
                MemoryPageState.EMPTY,
                MemoryPageState.MUTATION_ERROR,
            }
        ):
            return False
        self._memory_editor_mode = "CREATE"
        self._memory_editor_request = None
        self.memory_errors.replace(())
        self.memory_editor_type = MemoryType.PROJECT_FACT.value
        self.memory_editor_scope = MemoryScope.CONVERSATION.value
        self.memory_editor_content = ""
        self.memory_editor_keywords = ""
        self.memory_editor_topics = ""
        self.memory_editor_importance = "0.5"
        self.memory_editor_confidence = "0.5"
        self.memory_editor_expiry = ""
        self.memory_state = MemoryPageState.EDITING
        self.memory_status = ""
        self._notify()
        return True

    def begin_edit_memory(self) -> bool:
        if (
            self._route is not Route.MEMORY
            or self._active is not None
            or self._selected_memory_index is None
            or self._memory_filter is MemoryStatus.DELETED
            or self.memory_state is not MemoryPageState.READY
        ):
            return False
        self._memory_editor_mode = "EDIT"
        self.memory_errors.replace(())
        selected = self._memory_views[self._selected_memory_index]
        self.memory_editor_type = selected.summary.type.code
        self.memory_editor_scope = selected.summary.scope.code
        self.memory_editor_content = selected.details.content
        self.memory_editor_keywords = "\n".join(selected.details.keywords)
        self.memory_editor_topics = "\n".join(selected.details.topic_terms)
        self.memory_editor_importance = selected.details.importance.display_text
        self.memory_editor_confidence = selected.details.confidence.display_text
        self.memory_editor_expiry = (
            ""
            if selected.details.expires_at_text == "Does not expire."
            else selected.details.expires_at_text
        )
        self.memory_state = MemoryPageState.EDITING
        self.memory_status = ""
        self._notify()
        return True

    @staticmethod
    def _decimal_or_raw(value: str) -> object:
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return value

    @staticmethod
    def _expiry_or_raw(value: str) -> object:
        if value == "":
            return None
        try:
            normalized = value.replace(" UTC", "+00:00").replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return value

    def submit_memory_editor(
        self,
        memory_type: str,
        scope: str,
        content: str,
        keywords_text: str,
        topics_text: str,
        importance: str,
        confidence: str,
        expiry: str,
        source_description: str,
    ) -> bool:
        if (
            self._route is not Route.MEMORY
            or self.memory_state is not MemoryPageState.EDITING
            or self._active is not None
            or self._conversation_id is None
        ):
            return False
        keywords = () if keywords_text == "" else tuple(keywords_text.split("\n"))
        topics = () if topics_text == "" else tuple(topics_text.split("\n"))
        score_importance = self._decimal_or_raw(importance)
        score_confidence = self._decimal_or_raw(confidence)
        expires_at = self._expiry_or_raw(expiry)
        if self._memory_editor_mode == "CREATE":
            try:
                parsed_type: object = MemoryType(memory_type)
            except ValueError:
                parsed_type = memory_type
            try:
                parsed_scope: object = MemoryScope(scope)
            except ValueError:
                parsed_scope = scope
            request = CreateMemoryPresentationRequest(
                conversation_id=self._conversation_id,
                memory_type=parsed_type,  # type: ignore[arg-type]
                scope=parsed_scope,  # type: ignore[arg-type]
                content=content,
                keywords=keywords,
                topic_terms=topics,
                importance=score_importance,  # type: ignore[arg-type]
                confidence=score_confidence,  # type: ignore[arg-type]
                expires_at=expires_at,  # type: ignore[arg-type]
                source_description=source_description,
                duplicate_decision=MemoryDuplicateDecision.CHECK,
            )
            self._memory_editor_request = request
            return self._start_mutation(
                Route.MEMORY,
                ManualOperationKind.CREATE_MEMORY,
                request,
                "Creating memory.",
            )
        if self._selected_memory_index is None:
            return False
        selected = self._memory_views[self._selected_memory_index]
        if selected.private_memory_id is None:
            return False
        request = EditMemoryPresentationRequest(
            memory_id=selected.private_memory_id,
            expected_revision_number=selected.details.revisions[-1].revision_number,
            content=content,
            keywords=keywords,
            topic_terms=topics,
            importance=score_importance,  # type: ignore[arg-type]
            confidence=score_confidence,  # type: ignore[arg-type]
            expires_at=expires_at,  # type: ignore[arg-type]
            source_description=source_description,
        )
        return self._start_mutation(
            Route.MEMORY,
            ManualOperationKind.EDIT_MEMORY,
            request,
            "Updating memory.",
        )

    def return_from_duplicate_guidance(self) -> bool:
        if self.memory_state is not MemoryPageState.DUPLICATE_GUIDANCE:
            return False
        self.memory_duplicates.replace(())
        self.memory_state = MemoryPageState.EDITING
        self.memory_status = ""
        self._notify()
        return True

    def proceed_with_duplicate_create(self) -> bool:
        request = self._memory_editor_request
        if (
            self.memory_state is not MemoryPageState.DUPLICATE_GUIDANCE
            or request is None
            or self._active is not None
        ):
            return False
        return self._start_mutation(
            Route.MEMORY,
            ManualOperationKind.CREATE_MEMORY,
            replace(request, duplicate_decision=MemoryDuplicateDecision.PROCEED),
            "Creating memory.",
        )

    def request_memory_soft_delete(self) -> bool:
        if (
            self._route is not Route.MEMORY
            or self.memory_state is not MemoryPageState.READY
            or self._selected_memory_index is None
            or self._memory_filter is MemoryStatus.DELETED
        ):
            return False
        self.memory_state = MemoryPageState.DELETE_CONFIRMATION
        self._notify()
        return True

    def cancel_memory_soft_delete(self) -> bool:
        if self.memory_state is not MemoryPageState.DELETE_CONFIRMATION:
            return False
        self.memory_state = MemoryPageState.READY
        self._notify()
        return True

    def confirm_memory_soft_delete(self, description: str) -> bool:
        if (
            self.memory_state is not MemoryPageState.DELETE_CONFIRMATION
            or self._selected_memory_index is None
            or not isinstance(description, str)
            or not description.strip()
        ):
            return False
        selected = self._memory_views[self._selected_memory_index]
        if selected.private_memory_id is None:
            return False
        return self._start_mutation(
            Route.MEMORY,
            ManualOperationKind.SOFT_DELETE_MEMORY,
            SoftDeleteMemoryPresentationRequest(
                selected.private_memory_id,
                selected.details.revisions[-1].revision_number,
                description,
            ),
            "Soft-deleting memory.",
        )

    def select_active_project(self, row: int) -> bool:
        if (
            self._route is not Route.PROJECTS
            or self.projects_state is not ProjectsPageState.READY
            or self._active is not None
            or not isinstance(row, int)
            or isinstance(row, bool)
            or row not in range(len(self._active_project_views))
        ):
            return False
        item = self._active_project_views[row]
        if item.private_project_id is None or item.is_current_association:
            return False
        return self._start_mutation(
            Route.PROJECTS,
            ManualOperationKind.SELECT_PROJECT,
            SelectProjectPresentationRequest(
                self._conversation_id,  # type: ignore[arg-type]
                item.private_project_id,
                self._project_state_version,
            ),
            "Changing project selection.",
        )

    def clear_project_selection(self) -> bool:
        if (
            self._route is not Route.PROJECTS
            or self.projects_state is not ProjectsPageState.READY
            or self._active is not None
            or not any(
                item.is_current_association
                for item in (
                    *self._active_project_views,
                    *self._archived_project_views,
                )
            )
        ):
            return False
        return self._start_mutation(
            Route.PROJECTS,
            ManualOperationKind.SELECT_PROJECT,
            SelectProjectPresentationRequest(
                self._conversation_id,  # type: ignore[arg-type]
                None,
                self._project_state_version,
            ),
            "Changing project selection.",
        )

    def request_project_archive(self, row: int) -> bool:
        if (
            self._route is not Route.PROJECTS
            or self.projects_state is not ProjectsPageState.READY
            or not isinstance(row, int)
            or isinstance(row, bool)
            or row not in range(len(self._active_project_views))
            or not self._active_project_views[row].archive_eligible
        ):
            return False
        self._archive_target = self._active_project_views[row]
        self.projects_state = ProjectsPageState.ARCHIVE_CONFIRMATION
        self._notify()
        return True

    def cancel_project_archive(self) -> bool:
        if self.projects_state is not ProjectsPageState.ARCHIVE_CONFIRMATION:
            return False
        self._archive_target = None
        self.projects_state = ProjectsPageState.READY
        self._notify()
        return True

    def confirm_project_archive(self) -> bool:
        target = self._archive_target
        if (
            self.projects_state is not ProjectsPageState.ARCHIVE_CONFIRMATION
            or target is None
            or target.private_project_id is None
        ):
            return False
        return self._start_mutation(
            Route.PROJECTS,
            ManualOperationKind.ARCHIVE_PROJECT,
            ArchiveProjectPresentationRequest(
                target.private_project_id,
                target.is_current_association,
            ),
            "Archiving project.",
        )

    def set_pending_theme(self, value: str) -> bool:
        if self._route is not Route.SETTINGS or self._active is not None:
            return False
        try:
            theme = UiTheme(value)
        except ValueError:
            return False
        if theme is self._pending_theme:
            return False
        self._pending_theme = theme
        self._notify()
        return True

    def set_pending_context_panel_visible(self, value: bool) -> bool:
        if (
            self._route is not Route.SETTINGS
            or self._active is not None
            or not isinstance(value, bool)
            or value == self._pending_context_visible
        ):
            return False
        self._pending_context_visible = value
        self._notify()
        return True

    def save_settings(self) -> bool:
        if not self.settings_save_enabled:
            return False
        updates: list[SettingUpdate] = []
        if self._pending_theme is not self._theme:
            updates.append(SettingUpdate(ManualSettingKey.UI_THEME.value, self._pending_theme))
        if self._pending_context_visible != self._context_visible:
            updates.append(
                SettingUpdate(
                    ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE.value,
                    self._pending_context_visible,
                )
            )
        return self._start_mutation(
            Route.SETTINGS,
            ManualOperationKind.UPDATE_MANUAL_SETTINGS,
            UpdateManualSettingsRequest(tuple(updates)),
            "Saving settings.",
        )

    def current_conversation_terminal(self, conversation_id: DomainId) -> None:
        if conversation_id != self._conversation_id or self._disposed:
            return
        self._dirty[Route.VALIDATION_HISTORY] = True
        if self._route is Route.VALIDATION_HISTORY:
            self._request_read(Route.VALIDATION_HISTORY, refreshed=True)

    def current_conversation_changed(self, conversation_id: DomainId) -> None:
        self._conversation_id = conversation_id
        self._generation += 1
        for route in self._dirty:
            self._dirty[route] = True
        if self._route in _QUERY_KIND_BY_ROUTE:
            self._request_read(self._route, refreshed=True)

    def request_shutdown(self) -> None:
        if self._shutdown_state():
            return
        self._generation += 1
        self._pending_read_route = None
        self.memory_state = MemoryPageState.SHUTDOWN
        self.projects_state = ProjectsPageState.SHUTDOWN
        self.validation_state = ValidationHistoryPageState.SHUTDOWN
        self.settings_state = SettingsPageState.SHUTDOWN
        self.memory_status = ""
        self.projects_status = ""
        self.validation_status = ""
        self.settings_status = ""
        self._clear_memory()
        self._clear_projects()
        self.validation_attempts.replace(())
        self.validation_corrections.replace(())
        self.validation_summary.replace(())
        self.configuration_fields.replace(())
        self._notify()

    def _shutdown_state(self) -> bool:
        return self.memory_state is MemoryPageState.SHUTDOWN

    def dispose(self) -> None:
        self._disposed = True
        self._generation += 1
        self._pending_read_route = None
        self._active = None
        self._clear_memory()
        self._clear_projects()


__all__ = [
    "ManualListModel",
    "ManualListRow",
    "ManualOperationsController",
    "ManualOperationsWorker",
]
