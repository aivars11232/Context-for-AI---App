"""One GUI-owned QML facade with three finite worker ownership roles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    QThread,
    Qt,
    Signal,
    Slot,
)

from context_for_ai.application import (
    CancellationCheckpoint,
    CancelledResult,
    ClarificationResult,
    ConcurrencyConflictResult,
    ControlledFailureResult,
    DomainId,
    IdempotencyKeyFactory,
    InspectContextRequest,
    InitialUiPreferences,
    PersistenceFailureResult,
    ProcessUserMessageRequest,
    RecoverProcessingRunRequest,
    RecoveryCompletedResult,
    RecoveryRequiredResult,
    ShellApplicationScopeFactory,
    ShellReadyResult,
    SucceededResult,
    UiTheme,
    ValidationExhaustedResult,
)
from context_for_ai.ui.manual_operations import ManualOperationsController
from context_for_ai.ui.presentation import (
    ContextInspectionPageState,
    ContextInspectionPresentationView,
    ExecutionKind,
    ForegroundExecutionFailureView,
    ForegroundTerminalEnvelope,
    InspectionCollectionPresentation,
    InspectionExecutionFailureView,
    InspectionListItemPresentation,
    InspectionScalarPresentation,
    InspectionTerminalEnvelope,
    MonotonicCancellationToken,
    MemoryPageState,
    ProjectsPageState,
    Route,
    SettingsPageState,
    ShellState,
    TerminalPresentationView,
    ValidationHistoryPageState,
    contained_foreground_result,
    contained_inspection_result,
    inspection_result_presentation,
    terminal_presentation_view,
)


_PROGRESS_LABELS = {
    ShellState.STARTUP: "Starting…",
    ShellState.RECOVERY: "Recovering an interrupted request…",
    ShellState.PENDING: "Processing…",
    ShellState.CANCELLATION_REQUESTED: "Cancelling…",
}


def _creates_current_conversation_terminal(result: object) -> bool:
    if isinstance(result, RecoveryCompletedResult):
        return _creates_current_conversation_terminal(result.outcome)
    if isinstance(
        result,
        (
            SucceededResult,
            ClarificationResult,
            ValidationExhaustedResult,
            ConcurrencyConflictResult,
            ControlledFailureResult,
        ),
    ):
        return True
    if isinstance(result, CancelledResult):
        return result.checkpoint is not CancellationCheckpoint.BEFORE_ACCEPTANCE
    if isinstance(result, PersistenceFailureResult):
        return result.failure_persisted
    return False


def _role(offset: int) -> int:
    return int(Qt.ItemDataRole.UserRole) + offset


class _ScalarListModel(QAbstractListModel):
    """Read-only scalar rows whose role values are primitive strings."""

    _LABEL = _role(1)
    _DISPLAY_TEXT = _role(2)
    _ACCESSIBLE_NAME = _role(3)
    _ROLES = {
        _LABEL: QByteArray(b"label"),
        _DISPLAY_TEXT: QByteArray(b"displayText"),
        _ACCESSIBLE_NAME: QByteArray(b"accessibleName"),
    }

    def __init__(
        self,
        values: tuple[InspectionScalarPresentation, ...],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._values = tuple(values)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt override
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._values)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._values):
            return None
        value = self._values[index.row()]
        return {
            self._LABEL: value.label,
            self._DISPLAY_TEXT: value.display_text,
            self._ACCESSIBLE_NAME: value.accessible_name,
        }.get(role)


@dataclass(frozen=True, slots=True)
class _ItemModelRow:
    accessible_name: str
    scalars: _ScalarListModel
    collections: _CollectionListModel


class _ItemListModel(QAbstractListModel):
    """Read-only list-item rows with recursively safe child models."""

    _ACCESSIBLE_NAME = _role(1)
    _SCALARS = _role(2)
    _COLLECTIONS = _role(3)
    _ROLES = {
        _ACCESSIBLE_NAME: QByteArray(b"accessibleName"),
        _SCALARS: QByteArray(b"scalars"),
        _COLLECTIONS: QByteArray(b"collections"),
    }

    def __init__(
        self,
        values: tuple[InspectionListItemPresentation, ...],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._values = tuple(
            _ItemModelRow(
                value.accessible_name,
                _ScalarListModel(value.scalars, self),
                _CollectionListModel(value.collections, self),
            )
            for value in values
        )

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt override
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._values)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._values):
            return None
        value = self._values[index.row()]
        return {
            self._ACCESSIBLE_NAME: value.accessible_name,
            self._SCALARS: value.scalars,
            self._COLLECTIONS: value.collections,
        }.get(role)


@dataclass(frozen=True, slots=True)
class _CollectionModelRow:
    accessible_id: str
    accessible_name: str
    availability: str
    display_text: str
    items: _ItemListModel


class _CollectionListModel(QAbstractListModel):
    """Read-only collection metadata and list-item child models."""

    _ACCESSIBLE_ID = _role(1)
    _ACCESSIBLE_NAME = _role(2)
    _AVAILABILITY = _role(3)
    _DISPLAY_TEXT = _role(4)
    _ITEMS = _role(5)
    _ROLES = {
        _ACCESSIBLE_ID: QByteArray(b"accessibleId"),
        _ACCESSIBLE_NAME: QByteArray(b"accessibleName"),
        _AVAILABILITY: QByteArray(b"availability"),
        _DISPLAY_TEXT: QByteArray(b"displayText"),
        _ITEMS: QByteArray(b"items"),
    }

    def __init__(
        self,
        values: tuple[InspectionCollectionPresentation, ...],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._values = tuple(
            _CollectionModelRow(
                value.accessible_id,
                value.accessible_name,
                value.availability,
                value.display_text,
                _ItemListModel(value.items, self),
            )
            for value in values
        )

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt override
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._values)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._values):
            return None
        value = self._values[index.row()]
        return {
            self._ACCESSIBLE_ID: value.accessible_id,
            self._ACCESSIBLE_NAME: value.accessible_name,
            self._AVAILABILITY: value.availability,
            self._DISPLAY_TEXT: value.display_text,
            self._ITEMS: value.items,
        }.get(role)


@dataclass(frozen=True, slots=True)
class _SectionModelRow:
    accessible_id: str
    accessible_name: str
    scalars: _ScalarListModel
    collections: _CollectionListModel


class _InspectionSectionListModel(QAbstractListModel):
    """Replaceable root model for the exact nine-section inspection tree."""

    _ACCESSIBLE_ID = _role(1)
    _ACCESSIBLE_NAME = _role(2)
    _SCALARS = _role(3)
    _COLLECTIONS = _role(4)
    _ROLES = {
        _ACCESSIBLE_ID: QByteArray(b"accessibleId"),
        _ACCESSIBLE_NAME: QByteArray(b"accessibleName"),
        _SCALARS: QByteArray(b"scalars"),
        _COLLECTIONS: QByteArray(b"collections"),
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[_SectionModelRow, ...] = ()
        self._owned_models: tuple[QObject, ...] = ()

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt override
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._values)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._values):
            return None
        value = self._values[index.row()]
        return {
            self._ACCESSIBLE_ID: value.accessible_id,
            self._ACCESSIBLE_NAME: value.accessible_name,
            self._SCALARS: value.scalars,
            self._COLLECTIONS: value.collections,
        }.get(role)

    def replace(self, view: ContextInspectionPresentationView | None) -> None:
        old_models = self._owned_models
        self.beginResetModel()
        if view is None:
            self._values = ()
            self._owned_models = ()
        else:
            rows: list[_SectionModelRow] = []
            owned: list[QObject] = []
            for section in view.sections:
                scalars = _ScalarListModel(section.scalars, self)
                collections = _CollectionListModel(section.collections, self)
                rows.append(
                    _SectionModelRow(
                        section.accessible_id,
                        section.accessible_name,
                        scalars,
                        collections,
                    )
                )
                owned.extend((scalars, collections))
            self._values = tuple(rows)
            self._owned_models = tuple(owned)
        self.endResetModel()
        for model in old_models:
            model.deleteLater()


class _InspectionWorker(QObject):
    """Run exactly one read-only inspection scope on its owning thread."""

    terminal = Signal(object)
    work_complete = Signal()

    def __init__(
        self,
        *,
        generation: int,
        conversation_id: DomainId,
        scope_factory: ShellApplicationScopeFactory,
    ) -> None:
        super().__init__()
        self._generation = generation
        self._conversation_id = conversation_id
        self._scope_factory = scope_factory

    @Slot()
    def run(self) -> None:
        result: object = InspectionExecutionFailureView()
        scope: Any | None = None
        try:
            scope = self._scope_factory.open_inspection_scope()
            result = scope.inspect_context.execute(
                InspectContextRequest(self._conversation_id)
            )
        except BaseException:
            result = InspectionExecutionFailureView()
        finally:
            if scope is not None:
                try:
                    scope.close()
                except BaseException:
                    result = InspectionExecutionFailureView()

        self.terminal.emit(
            InspectionTerminalEnvelope(
                self._generation,
                self._conversation_id,
                contained_inspection_result(result),
            )
        )
        self.work_complete.emit()


@dataclass(slots=True)
class _ActiveInspection:
    generation: int
    conversation_id: DomainId
    refreshed: bool
    thread: QThread
    worker: _InspectionWorker
    terminal_consumed: bool = False
    thread_finished: bool = False


class _InspectionController:
    """Private finite inspection state and QThread ownership role."""

    _REFRESHABLE_STATES = frozenset(
        {
            ContextInspectionPageState.READY,
            ContextInspectionPageState.EMPTY,
            ContextInspectionPageState.CLARIFICATION,
            ContextInspectionPageState.CONTROLLED_FAILURE,
            ContextInspectionPageState.LOAD_ERROR,
        }
    )

    def __init__(
        self,
        *,
        owner: ShellFacade,
        scope_factory: ShellApplicationScopeFactory,
    ) -> None:
        self._owner = owner
        self._scope_factory = scope_factory
        self._route = Route.CHAT
        self._state = ContextInspectionPageState.INACTIVE
        self._conversation_id: DomainId | None = None
        self._status_text = ""
        self._announcement_text = ""
        self._announcement_revision = 0
        self._sections = _InspectionSectionListModel(owner)
        self._active: _ActiveInspection | None = None
        self._generation = 0
        self._refresh_required = False
        self._coalesced_refreshed = True
        self._disposed = False

    @property
    def route(self) -> Route:
        return self._route

    @property
    def state(self) -> ContextInspectionPageState:
        return self._state

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def refresh_enabled(self) -> bool:
        return bool(
            not self._disposed
            and self._route is Route.CONTEXT_INSPECTION
            and self._state in self._REFRESHABLE_STATES
        )

    @property
    def announcement_text(self) -> str:
        return self._announcement_text

    @property
    def announcement_revision(self) -> int:
        return self._announcement_revision

    @property
    def sections(self) -> _InspectionSectionListModel:
        return self._sections

    @property
    def active_generation(self) -> int | None:
        return None if self._active is None else self._active.generation

    @property
    def refresh_required(self) -> bool:
        return self._refresh_required

    def _notify(self) -> None:
        self._owner.changed.emit()

    def _announce(self, text: str) -> None:
        self._announcement_text = text
        self._announcement_revision += 1

    def set_initial_conversation(self, conversation_id: DomainId) -> None:
        if self._disposed or self._conversation_id is not None:
            raise RuntimeError("Initial inspection conversation may be set once.")
        if not isinstance(conversation_id, DomainId):
            raise TypeError("Inspection conversation requires a domain ID.")
        self._conversation_id = conversation_id

    def navigate_to_chat(self) -> bool:
        return self.navigate_away(Route.CHAT)

    def navigate_away(self, route: Route) -> bool:
        if self._disposed or self._conversation_id is None or self._state is ContextInspectionPageState.SHUTDOWN:
            return False
        if not isinstance(route, Route) or route is Route.CONTEXT_INSPECTION:
            return False
        if self._route is route:
            return True
        self._route = route
        self._generation += 1
        self._refresh_required = False
        self._state = ContextInspectionPageState.INACTIVE
        self._status_text = ""
        self._sections.replace(None)
        self._notify()
        return True

    def navigate_to_context_inspection(self) -> bool:
        if self._disposed or self._conversation_id is None or self._state is ContextInspectionPageState.SHUTDOWN:
            return False
        refreshed = self._route is Route.CONTEXT_INSPECTION
        self._route = Route.CONTEXT_INSPECTION
        self._request_load(refreshed=refreshed)
        return True

    def refresh(self) -> bool:
        if (
            self._disposed
            or self._conversation_id is None
            or self._route is not Route.CONTEXT_INSPECTION
            or self._state is ContextInspectionPageState.SHUTDOWN
        ):
            return False
        self._request_load(refreshed=True)
        return True

    def _request_load(self, *, refreshed: bool) -> None:
        conversation_id = self._conversation_id
        if conversation_id is None:
            raise RuntimeError("Inspection load requires a conversation.")
        self._generation += 1
        generation = self._generation
        self._state = ContextInspectionPageState.LOADING
        self._status_text = "Loading context inspection…"
        self._sections.replace(None)
        self._announce("Loading context inspection.")
        if self._active is None:
            self._start_query(generation, conversation_id, refreshed)
        else:
            self._refresh_required = True
            self._coalesced_refreshed = refreshed
        self._notify()

    def _start_query(
        self,
        generation: int,
        conversation_id: DomainId,
        refreshed: bool,
    ) -> None:
        if self._active is not None or self._disposed:
            raise RuntimeError("Only one inspection worker may be owned.")
        thread = QThread(self._owner)
        thread.setObjectName(f"contextForAiInspection{generation}")
        worker = _InspectionWorker(
            generation=generation,
            conversation_id=conversation_id,
            scope_factory=self._scope_factory,
        )
        worker.moveToThread(thread)
        active = _ActiveInspection(
            generation,
            conversation_id,
            refreshed,
            thread,
            worker,
        )
        self._active = active

        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.terminal.connect(
            self._owner._inspection_terminal_received,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.work_complete.connect(worker.deleteLater)
        worker.work_complete.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(
            self._owner._inspection_thread_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        thread.finished.connect(thread.deleteLater)
        try:
            thread.start()
        except BaseException:
            active.terminal_consumed = True
            active.thread_finished = True
            if self._may_apply(active.generation, active.conversation_id):
                self._apply_result(InspectionExecutionFailureView(), active.refreshed)
            self._release_if_complete(active)

    def _may_apply(self, generation: int, conversation_id: DomainId) -> bool:
        return bool(
            not self._disposed
            and self._state is not ContextInspectionPageState.SHUTDOWN
            and self._route is Route.CONTEXT_INSPECTION
            and generation == self._generation
            and conversation_id == self._conversation_id
        )

    def receive_terminal(self, envelope: object) -> None:
        if self._disposed or not isinstance(envelope, InspectionTerminalEnvelope):
            return
        active = self._active
        if (
            active is None
            or active.terminal_consumed
            or envelope.generation != active.generation
            or envelope.conversation_id != active.conversation_id
        ):
            return
        active.terminal_consumed = True
        if self._may_apply(envelope.generation, envelope.conversation_id):
            self._apply_result(envelope.result, active.refreshed)
        self._release_if_complete(active)

    def _apply_result(self, result: object, refreshed: bool) -> None:
        try:
            projection = inspection_result_presentation(
                contained_inspection_result(result),
                refreshed=refreshed,
            )
        except BaseException:
            projection = inspection_result_presentation(
                InspectionExecutionFailureView(),
                refreshed=refreshed,
            )
        self._state = projection.state
        self._status_text = projection.status_text
        self._sections.replace(projection.view)
        self._announce(projection.announcement_text)
        self._notify()

    def receive_thread_finished(self, thread: object) -> None:
        active = self._active
        if self._disposed or active is None or thread is not active.thread:
            return
        if active.thread_finished:
            return
        active.thread_finished = True
        self._release_if_complete(active)

    def _release_if_complete(self, active: _ActiveInspection) -> None:
        if (
            self._active is not active
            or not active.terminal_consumed
            or not active.thread_finished
        ):
            return
        self._active = None
        if (
            self._refresh_required
            and not self._disposed
            and self._state is not ContextInspectionPageState.SHUTDOWN
            and self._route is Route.CONTEXT_INSPECTION
            and self._conversation_id is not None
        ):
            self._refresh_required = False
            self._start_query(
                self._generation,
                self._conversation_id,
                self._coalesced_refreshed,
            )
        else:
            self._refresh_required = False
        self._notify()
        if self._state is ContextInspectionPageState.SHUTDOWN:
            self._owner._owned_worker_released()

    def current_conversation_changed(self, conversation_id: DomainId) -> bool:
        if (
            self._disposed
            or self._state is ContextInspectionPageState.SHUTDOWN
            or not isinstance(conversation_id, DomainId)
            or conversation_id == self._conversation_id
        ):
            return False
        self._conversation_id = conversation_id
        if self._route is Route.CONTEXT_INSPECTION:
            self._request_load(refreshed=True)
        else:
            self._generation += 1
            self._sections.replace(None)
            self._status_text = ""
            self._notify()
        return True

    def current_project_changed(self) -> bool:
        if (
            self._disposed
            or self._state is ContextInspectionPageState.SHUTDOWN
            or self._route is not Route.CONTEXT_INSPECTION
        ):
            return False
        self._request_load(refreshed=True)
        return True

    def current_conversation_terminal(self, conversation_id: DomainId) -> bool:
        if conversation_id != self._conversation_id:
            return False
        return self.current_project_changed()

    def request_shutdown(self) -> None:
        if self._disposed or self._state is ContextInspectionPageState.SHUTDOWN:
            return
        self._state = ContextInspectionPageState.SHUTDOWN
        self._generation += 1
        self._refresh_required = False
        self._status_text = ""
        self._sections.replace(None)
        self._notify()

    def dispose(self) -> None:
        self._disposed = True
        self._generation += 1
        self._refresh_required = False
        self._sections.replace(None)
        self._active = None


class _ForegroundWorker(QObject):
    terminal = Signal(object)
    work_complete = Signal()

    def __init__(
        self,
        *,
        execution_id: int,
        execution_kind: ExecutionKind,
        request: object,
        cancellation_token: MonotonicCancellationToken,
        scope_factory: ShellApplicationScopeFactory,
    ) -> None:
        super().__init__()
        self._execution_id = execution_id
        self._execution_kind = execution_kind
        self._request = request
        self._cancellation_token = cancellation_token
        self._scope_factory = scope_factory

    @Slot()
    def run(self) -> None:
        result: object = ForegroundExecutionFailureView(self._execution_kind)
        scope: Any | None = None
        try:
            scope = self._scope_factory.open_foreground_scope()
            if self._execution_kind is ExecutionKind.SUBMISSION:
                result = scope.process_user_message.execute(
                    self._request,
                    self._cancellation_token,
                )
            else:
                result = scope.recover_processing_run.execute(
                    self._request,
                    self._cancellation_token,
                )
        except BaseException:
            result = ForegroundExecutionFailureView(self._execution_kind)
        finally:
            if scope is not None:
                try:
                    scope.close()
                except BaseException:
                    result = ForegroundExecutionFailureView(
                        self._execution_kind
                    )

        contained = contained_foreground_result(self._execution_kind, result)
        self.terminal.emit(
            ForegroundTerminalEnvelope(
                self._execution_id,
                self._execution_kind,
                contained,
            )
        )
        self.work_complete.emit()


@dataclass(slots=True)
class _ActiveExecution:
    execution_id: int
    execution_kind: ExecutionKind
    token: MonotonicCancellationToken
    thread: QThread
    worker: _ForegroundWorker
    terminal_consumed: bool = False
    thread_finished: bool = False


class _ForegroundRunController:
    """Private state/ownership role of the one public shell facade."""

    def __init__(
        self,
        *,
        owner: ShellFacade,
        scope_factory: ShellApplicationScopeFactory,
        idempotency_keys: IdempotencyKeyFactory,
    ) -> None:
        self._owner = owner
        self._scope_factory = scope_factory
        self._idempotency_keys = idempotency_keys
        self._state = ShellState.STARTUP
        self._conversation_id: object | None = None
        self._root_loaded = False
        self._active: _ActiveExecution | None = None
        self._next_execution_id = 1
        self._terminal_view = TerminalPresentationView(ShellState.STARTUP)
        self._submission_permitted = False
        self._disposed = False

    @property
    def state(self) -> ShellState:
        return self._state

    @property
    def conversation_id(self) -> str:
        return "" if self._conversation_id is None else str(self._conversation_id)

    @property
    def terminal_view(self) -> TerminalPresentationView:
        return self._terminal_view

    @property
    def active_execution_id(self) -> int | None:
        return None if self._active is None else self._active.execution_id

    @property
    def input_enabled(self) -> bool:
        return bool(
            self._root_loaded
            and self._conversation_id is not None
            and self._active is None
            and not self._disposed
            and self._state is not ShellState.SHUTDOWN
            and self._submission_permitted
        )

    @property
    def submit_enabled(self) -> bool:
        return self.input_enabled

    @property
    def cancel_enabled(self) -> bool:
        return bool(
            self._active is not None
            and self._state in {ShellState.RECOVERY, ShellState.PENDING}
            and not self._active.token.is_cancelled()
            and not self._disposed
        )

    @property
    def progress_visible(self) -> bool:
        if self._state is ShellState.SHUTDOWN:
            return self._active is not None
        return self._state in _PROGRESS_LABELS

    @property
    def progress_label(self) -> str:
        if self._state is ShellState.SHUTDOWN:
            return "Closing safely…" if self._active is not None else ""
        return _PROGRESS_LABELS.get(self._state, "")

    def _notify(self) -> None:
        self._owner.changed.emit()

    def apply_preparation(
        self,
        result: ShellReadyResult | RecoveryRequiredResult,
    ) -> None:
        if self._disposed or self._root_loaded or self._state is not ShellState.STARTUP:
            raise RuntimeError("Shell preparation may be published exactly once.")
        if not isinstance(result, (ShellReadyResult, RecoveryRequiredResult)):
            raise TypeError("Shell facade requires one successful preparation result.")
        self._root_loaded = True
        self._conversation_id = result.conversation_id
        self._clear_terminal(ShellState.IDLE)
        if isinstance(result, ShellReadyResult):
            self._state = ShellState.IDLE
            self._submission_permitted = True
            self._notify()
            return

        self._state = ShellState.RECOVERY
        self._submission_permitted = False
        self._begin_execution(
            ExecutionKind.RECOVERY,
            RecoverProcessingRunRequest(),
        )

    def _clear_terminal(self, state: ShellState) -> None:
        self._terminal_view = TerminalPresentationView(state)

    def submit_exact(self, user_text: object) -> bool:
        if (
            not isinstance(user_text, str)
            or user_text == ""
            or not self.submit_enabled
            or self._conversation_id is None
        ):
            return False

        idempotency_key = self._idempotency_keys.new_key()
        request = ProcessUserMessageRequest(
            conversation_id=self._conversation_id,  # type: ignore[arg-type]
            user_text=user_text,
            idempotency_key=idempotency_key,
            project_id=None,
        )
        self._state = ShellState.PENDING
        self._submission_permitted = False
        self._clear_terminal(ShellState.PENDING)
        self._begin_execution(ExecutionKind.SUBMISSION, request)
        return True

    def current_conversation_changed(self, conversation_id: DomainId) -> bool:
        if (
            self._disposed
            or self._state is ShellState.SHUTDOWN
            or self._active is not None
            or not isinstance(conversation_id, DomainId)
            or conversation_id == self._conversation_id
        ):
            return False
        self._conversation_id = conversation_id
        self._notify()
        return True

    def _begin_execution(
        self,
        execution_kind: ExecutionKind,
        request: object,
    ) -> None:
        if self._active is not None or self._disposed:
            raise RuntimeError("Only one foreground execution may be owned.")
        execution_id = self._next_execution_id
        self._next_execution_id += 1
        token = MonotonicCancellationToken()
        thread = QThread(self._owner)
        thread.setObjectName(f"contextForAiForeground{execution_id}")
        worker = _ForegroundWorker(
            execution_id=execution_id,
            execution_kind=execution_kind,
            request=request,
            cancellation_token=token,
            scope_factory=self._scope_factory,
        )
        worker.moveToThread(thread)
        active = _ActiveExecution(
            execution_id,
            execution_kind,
            token,
            thread,
            worker,
        )
        self._active = active

        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.terminal.connect(
            self._owner._terminal_received,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.work_complete.connect(worker.deleteLater)
        worker.work_complete.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(
            self._owner._thread_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        thread.finished.connect(thread.deleteLater)
        self._notify()
        try:
            thread.start()
        except BaseException:
            active.terminal_consumed = True
            active.thread_finished = True
            failure = ForegroundExecutionFailureView(execution_kind)
            if self._state is not ShellState.SHUTDOWN:
                self._apply_terminal_view(
                    terminal_presentation_view(execution_kind, failure)
                )
            self._release_if_complete(active)

    def request_cancellation(self) -> bool:
        active = self._active
        if active is None or not self.cancel_enabled:
            return False
        if not active.token.request_cancellation():
            return False
        self._state = ShellState.CANCELLATION_REQUESTED
        self._clear_terminal(ShellState.CANCELLATION_REQUESTED)
        self._submission_permitted = False
        self._notify()
        return True

    def receive_terminal(self, envelope: object) -> None:
        if self._disposed or not isinstance(envelope, ForegroundTerminalEnvelope):
            return
        active = self._active
        if (
            active is None
            or active.terminal_consumed
            or envelope.execution_id != active.execution_id
            or envelope.execution_kind is not active.execution_kind
        ):
            return
        active.terminal_consumed = True
        if self._state is not ShellState.SHUTDOWN:
            self._apply_terminal_view(
                terminal_presentation_view(
                    envelope.execution_kind,
                    envelope.result,
                )
            )
            if _creates_current_conversation_terminal(envelope.result):
                self._owner._current_conversation_terminal()
        self._release_if_complete(active)

    def _apply_terminal_view(self, view: TerminalPresentationView) -> None:
        self._terminal_view = view
        self._state = view.state
        self._submission_permitted = view.submission_permitted_after_cleanup
        self._notify()

    def receive_thread_finished(self, thread: object) -> None:
        active = self._active
        if self._disposed or active is None or thread is not active.thread:
            return
        if active.thread_finished:
            return
        active.thread_finished = True
        self._release_if_complete(active)

    def _release_if_complete(self, active: _ActiveExecution) -> None:
        if (
            self._active is not active
            or not active.terminal_consumed
            or not active.thread_finished
        ):
            return
        self._active = None
        self._notify()
        if self._state is ShellState.SHUTDOWN:
            self._owner._owned_worker_released()

    def request_shutdown(self) -> None:
        if self._disposed or self._state is ShellState.SHUTDOWN:
            return
        self._state = ShellState.SHUTDOWN
        self._submission_permitted = False
        self._clear_terminal(ShellState.SHUTDOWN)
        if self._active is not None:
            self._active.token.request_cancellation()
        self._notify()

    def dispose(self) -> None:
        self._disposed = True
        if self._active is not None:
            self._active.token.request_cancellation()
        self._active = None


class ShellFacade(QObject):
    """The sole GUI-thread-owned QObject and primitive QML presentation surface."""

    changed = Signal()
    shutdownReady = Signal()
    memoryAnnouncement = Signal(str, int)
    projectsAnnouncement = Signal(str, int)
    validationHistoryAnnouncement = Signal(str, int)
    settingsAnnouncement = Signal(str, int)

    def __init__(
        self,
        scope_factory: ShellApplicationScopeFactory,
        idempotency_keys: IdempotencyKeyFactory,
        parent: QObject | None = None,
        *,
        initial_preferences: InitialUiPreferences | None = None,
        theme_applier: Callable[[UiTheme], None] | None = None,
    ) -> None:
        super().__init__(parent)
        preferences = initial_preferences or InitialUiPreferences(UiTheme.SYSTEM, True)
        if not isinstance(preferences, InitialUiPreferences):
            raise TypeError("Shell facade requires closed initial UI preferences.")
        self._controller = _ForegroundRunController(
            owner=self,
            scope_factory=scope_factory,
            idempotency_keys=idempotency_keys,
        )
        self._inspection = _InspectionController(
            owner=self,
            scope_factory=scope_factory,
        )
        self._manual = ManualOperationsController(
            owner=self,
            scope_factory=scope_factory,
            theme_applier=theme_applier or (lambda _theme: None),
        )
        self._context_panel_visible = preferences.context_panel_visible
        self._manual.set_initial_preferences(
            theme=preferences.theme,
            context_panel_visible=preferences.context_panel_visible,
        )
        self._shutdown_requested = False
        self._shutdown_ready_emitted = False

    def _assert_gui_thread(self) -> None:
        if QThread.currentThread() is not self.thread():
            raise RuntimeError("ShellFacade may be used only on its GUI thread.")

    @Property(str, notify=changed)
    def route(self) -> str:
        return self._inspection.route.value

    @Property(bool, notify=changed)
    def context_navigation_visible(self) -> bool:
        return self._context_panel_visible

    @Property(str, notify=changed)
    def inspection_page_state(self) -> str:
        return self._inspection.state.value

    @Property(str, notify=changed)
    def inspection_status_text(self) -> str:
        return self._inspection.status_text

    @Property(bool, notify=changed)
    def inspection_refresh_enabled(self) -> bool:
        return self._inspection.refresh_enabled

    @Property(bool, notify=changed)
    def inspection_has_view(self) -> bool:
        return self._inspection.sections.rowCount() == 9

    @Property(QObject, notify=changed)
    def inspection_sections(self) -> QObject:
        return self._inspection.sections

    @Property(str, notify=changed)
    def inspection_announcement_text(self) -> str:
        return self._inspection.announcement_text

    @Property(int, notify=changed)
    def inspection_announcement_revision(self) -> int:
        return self._inspection.announcement_revision

    @Property(str, notify=changed)
    def memory_page_state(self) -> str:
        return self._manual.memory_state.value

    @Property(str, notify=changed)
    def memory_status_text(self) -> str:
        return self._manual.memory_status

    @Property(str, notify=changed)
    def memory_announcement_text(self) -> str:
        return self._manual.memory_announcement

    @Property(int, notify=changed)
    def memory_announcement_revision(self) -> int:
        return self._manual.memory_announcement_revision

    @Property(str, notify=changed)
    def memory_filter(self) -> str:
        return self._manual.memory_filter

    @Property(int, notify=changed)
    def selected_memory_index(self) -> int:
        return self._manual.selected_memory_index

    @Property(str, notify=changed)
    def memory_editor_mode(self) -> str:
        return self._manual.memory_editor_mode

    @Property(QObject, notify=changed)
    def memory_items(self) -> QObject:
        return self._manual.memory_items

    @Property(QObject, notify=changed)
    def memory_details(self) -> QObject:
        return self._manual.memory_details

    @Property(QObject, notify=changed)
    def memory_sources(self) -> QObject:
        return self._manual.memory_sources

    @Property(QObject, notify=changed)
    def memory_revisions(self) -> QObject:
        return self._manual.memory_revisions

    @Property(QObject, notify=changed)
    def memory_duplicates(self) -> QObject:
        return self._manual.memory_duplicates

    @Property(QObject, notify=changed)
    def memory_errors(self) -> QObject:
        return self._manual.memory_errors

    @Property(str, notify=changed)
    def memory_editor_type(self) -> str:
        return self._manual.memory_editor_type

    @Property(str, notify=changed)
    def memory_editor_scope(self) -> str:
        return self._manual.memory_editor_scope

    @Property(str, notify=changed)
    def memory_editor_content(self) -> str:
        return self._manual.memory_editor_content

    @Property(str, notify=changed)
    def memory_editor_keywords(self) -> str:
        return self._manual.memory_editor_keywords

    @Property(str, notify=changed)
    def memory_editor_topics(self) -> str:
        return self._manual.memory_editor_topics

    @Property(str, notify=changed)
    def memory_editor_importance(self) -> str:
        return self._manual.memory_editor_importance

    @Property(str, notify=changed)
    def memory_editor_confidence(self) -> str:
        return self._manual.memory_editor_confidence

    @Property(str, notify=changed)
    def memory_editor_expiry(self) -> str:
        return self._manual.memory_editor_expiry

    @Property(str, notify=changed)
    def projects_page_state(self) -> str:
        return self._manual.projects_state.value

    @Property(str, notify=changed)
    def projects_status_text(self) -> str:
        return self._manual.projects_status

    @Property(str, notify=changed)
    def projects_announcement_text(self) -> str:
        return self._manual.projects_announcement

    @Property(int, notify=changed)
    def projects_announcement_revision(self) -> int:
        return self._manual.projects_announcement_revision

    @Property(QObject, notify=changed)
    def active_projects(self) -> QObject:
        return self._manual.active_projects

    @Property(QObject, notify=changed)
    def archived_projects(self) -> QObject:
        return self._manual.archived_projects

    @Property(str, notify=changed)
    def validation_history_page_state(self) -> str:
        return self._manual.validation_state.value

    @Property(str, notify=changed)
    def validation_history_status_text(self) -> str:
        return self._manual.validation_status

    @Property(str, notify=changed)
    def validation_history_announcement_text(self) -> str:
        return self._manual.validation_announcement

    @Property(int, notify=changed)
    def validation_history_announcement_revision(self) -> int:
        return self._manual.validation_announcement_revision

    @Property(QObject, notify=changed)
    def validation_history_attempts(self) -> QObject:
        return self._manual.validation_attempts

    @Property(QObject, notify=changed)
    def validation_history_summary(self) -> QObject:
        return self._manual.validation_summary

    @Property(QObject, notify=changed)
    def validation_history_corrections(self) -> QObject:
        return self._manual.validation_corrections

    @Property(str, notify=changed)
    def settings_page_state(self) -> str:
        return self._manual.settings_state.value

    @Property(str, notify=changed)
    def settings_status_text(self) -> str:
        return self._manual.settings_status

    @Property(str, notify=changed)
    def settings_announcement_text(self) -> str:
        return self._manual.settings_announcement

    @Property(int, notify=changed)
    def settings_announcement_revision(self) -> int:
        return self._manual.settings_announcement_revision

    @Property(str, notify=changed)
    def settings_theme(self) -> str:
        return self._manual.theme

    @Property(str, notify=changed)
    def settings_pending_theme(self) -> str:
        return self._manual.pending_theme

    @Property(bool, notify=changed)
    def settings_context_panel_visible(self) -> bool:
        return self._manual.context_panel_visible

    @Property(bool, notify=changed)
    def settings_pending_context_panel_visible(self) -> bool:
        return self._manual.pending_context_panel_visible

    @Property(bool, notify=changed)
    def settings_save_enabled(self) -> bool:
        return self._manual.settings_save_enabled

    @Property(QObject, notify=changed)
    def settings_configuration(self) -> QObject:
        return self._manual.configuration_fields

    @Property(QObject, notify=changed)
    def settings_errors(self) -> QObject:
        return self._manual.settings_errors

    @Property(str, notify=changed)
    def settings_configuration_fingerprint(self) -> str:
        return self._manual.configuration_fingerprint

    @Property(str, notify=changed)
    def state(self) -> str:
        return self._controller.state.value

    @Property(str, notify=changed)
    def conversation_id(self) -> str:
        return self._controller.conversation_id

    @Property(bool, notify=changed)
    def input_enabled(self) -> bool:
        return self._controller.input_enabled

    @Property(bool, notify=changed)
    def submit_enabled(self) -> bool:
        return self._controller.submit_enabled

    @Property(bool, notify=changed)
    def cancel_enabled(self) -> bool:
        return self._controller.cancel_enabled

    @Property(bool, notify=changed)
    def progress_visible(self) -> bool:
        if self._controller.state is ShellState.SHUTDOWN:
            return bool(
                self._controller.active_execution_id is not None
                or self._inspection.active_generation is not None
                or self._manual.active_operation_id is not None
            )
        return self._controller.progress_visible

    @Property(str, notify=changed)
    def progress_label(self) -> str:
        if self._controller.state is ShellState.SHUTDOWN:
            return "Closing safely…" if self.progress_visible else ""
        return self._controller.progress_label

    @Property(str, notify=changed)
    def status_kind(self) -> str:
        return self._controller.terminal_view.status_kind

    @Property(str, notify=changed)
    def status_message(self) -> str:
        return self._controller.terminal_view.status_message

    @Property(str, notify=changed)
    def assistant_text(self) -> str:
        return self._controller.terminal_view.assistant_text

    @Property(str, notify=changed)
    def clarification_text(self) -> str:
        return self._controller.terminal_view.clarification_text

    def apply_preparation(
        self,
        result: ShellReadyResult | RecoveryRequiredResult,
    ) -> None:
        self._assert_gui_thread()
        if not isinstance(result, (ShellReadyResult, RecoveryRequiredResult)):
            raise TypeError("Shell facade requires one successful preparation result.")
        self._inspection.set_initial_conversation(result.conversation_id)
        self._manual.set_initial_conversation(result.conversation_id)
        self._controller.apply_preparation(result)

    @Slot(result=bool)
    def navigate_to_chat(self) -> bool:
        self._assert_gui_thread()
        previous = self._inspection.route
        accepted = self._inspection.navigate_to_chat()
        if accepted and previous is not Route.CHAT:
            self._manual.navigate_away(Route.CHAT)
        return accepted

    @Slot(result=bool)
    def navigate_to_context_inspection(self) -> bool:
        self._assert_gui_thread()
        if not self._context_panel_visible:
            return False
        previous = self._inspection.route
        accepted = self._inspection.navigate_to_context_inspection()
        if accepted and previous is not Route.CONTEXT_INSPECTION:
            self._manual.navigate_away(Route.CONTEXT_INSPECTION)
        return accepted

    @Slot(result=bool)
    def refresh_context_inspection(self) -> bool:
        self._assert_gui_thread()
        return self._inspection.refresh()

    def _navigate_to_manual(self, route: Route) -> bool:
        if not self._inspection.navigate_away(route):
            return False
        if not self._manual.navigate(route):
            raise RuntimeError("Shell route owners became inconsistent.")
        return True

    @Slot(result=bool)
    def navigate_to_memory(self) -> bool:
        self._assert_gui_thread()
        return self._navigate_to_manual(Route.MEMORY)

    @Slot(result=bool)
    def refresh_memories(self) -> bool:
        self._assert_gui_thread()
        return self._manual.refresh(Route.MEMORY)

    @Slot(str, result=bool)
    def set_memory_filter(self, value: str) -> bool:
        self._assert_gui_thread()
        return self._manual.set_memory_filter(value)

    @Slot(int, result=bool)
    def select_memory(self, row: int) -> bool:
        self._assert_gui_thread()
        return self._manual.select_memory(row)

    @Slot(result=bool)
    def begin_create_memory(self) -> bool:
        self._assert_gui_thread()
        return self._manual.begin_create_memory()

    @Slot(result=bool)
    def begin_edit_memory(self) -> bool:
        self._assert_gui_thread()
        return self._manual.begin_edit_memory()

    @Slot(str, str, str, str, str, str, str, str, str, result=bool)
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
        self._assert_gui_thread()
        return self._manual.submit_memory_editor(
            memory_type,
            scope,
            content,
            keywords_text,
            topics_text,
            importance,
            confidence,
            expiry,
            source_description,
        )

    @Slot(result=bool)
    def return_from_duplicate_guidance(self) -> bool:
        self._assert_gui_thread()
        return self._manual.return_from_duplicate_guidance()

    @Slot(result=bool)
    def proceed_with_duplicate_create(self) -> bool:
        self._assert_gui_thread()
        return self._manual.proceed_with_duplicate_create()

    @Slot(result=bool)
    def request_memory_soft_delete(self) -> bool:
        self._assert_gui_thread()
        return self._manual.request_memory_soft_delete()

    @Slot(result=bool)
    def cancel_memory_soft_delete(self) -> bool:
        self._assert_gui_thread()
        return self._manual.cancel_memory_soft_delete()

    @Slot(str, result=bool)
    def confirm_memory_soft_delete(self, source_description: str) -> bool:
        self._assert_gui_thread()
        return self._manual.confirm_memory_soft_delete(source_description)

    @Slot(result=bool)
    def navigate_to_projects(self) -> bool:
        self._assert_gui_thread()
        return self._navigate_to_manual(Route.PROJECTS)

    @Slot(result=bool)
    def refresh_projects(self) -> bool:
        self._assert_gui_thread()
        return self._manual.refresh(Route.PROJECTS)

    @Slot(int, result=bool)
    def select_active_project(self, row: int) -> bool:
        self._assert_gui_thread()
        return self._manual.select_active_project(row)

    @Slot(result=bool)
    def clear_project_selection(self) -> bool:
        self._assert_gui_thread()
        return self._manual.clear_project_selection()

    @Slot(int, result=bool)
    def request_project_archive(self, row: int) -> bool:
        self._assert_gui_thread()
        return self._manual.request_project_archive(row)

    @Slot(result=bool)
    def cancel_project_archive(self) -> bool:
        self._assert_gui_thread()
        return self._manual.cancel_project_archive()

    @Slot(result=bool)
    def confirm_project_archive(self) -> bool:
        self._assert_gui_thread()
        return self._manual.confirm_project_archive()

    @Slot(result=bool)
    def navigate_to_validation_history(self) -> bool:
        self._assert_gui_thread()
        return self._navigate_to_manual(Route.VALIDATION_HISTORY)

    @Slot(result=bool)
    def refresh_validation_history(self) -> bool:
        self._assert_gui_thread()
        return self._manual.refresh(Route.VALIDATION_HISTORY)

    @Slot(result=bool)
    def navigate_to_settings(self) -> bool:
        self._assert_gui_thread()
        return self._navigate_to_manual(Route.SETTINGS)

    @Slot(result=bool)
    def refresh_settings(self) -> bool:
        self._assert_gui_thread()
        return self._manual.refresh(Route.SETTINGS)

    @Slot(str, result=bool)
    def set_pending_theme(self, value: str) -> bool:
        self._assert_gui_thread()
        return self._manual.set_pending_theme(value)

    @Slot(bool, result=bool)
    def set_pending_context_panel_visible(self, value: bool) -> bool:
        self._assert_gui_thread()
        return self._manual.set_pending_context_panel_visible(value)

    @Slot(result=bool)
    def save_settings(self) -> bool:
        self._assert_gui_thread()
        return self._manual.save_settings()

    @Slot(str, result=bool)
    def submit_exact(self, user_text: str) -> bool:
        self._assert_gui_thread()
        return self._controller.submit_exact(user_text)

    @Slot(result=bool)
    def request_cancellation(self) -> bool:
        self._assert_gui_thread()
        return self._controller.request_cancellation()

    @Slot()
    def request_shutdown(self) -> None:
        self._assert_gui_thread()
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self._controller.request_shutdown()
        self._inspection.request_shutdown()
        self._manual.request_shutdown()
        self._maybe_emit_shutdown_ready()

    @Slot(object)
    def _terminal_received(self, envelope: object) -> None:
        self._assert_gui_thread()
        self._controller.receive_terminal(envelope)

    @Slot()
    def _thread_finished(self) -> None:
        self._assert_gui_thread()
        self._controller.receive_thread_finished(self.sender())

    @Slot(object)
    def _inspection_terminal_received(self, envelope: object) -> None:
        self._assert_gui_thread()
        self._inspection.receive_terminal(envelope)

    @Slot()
    def _inspection_thread_finished(self) -> None:
        self._assert_gui_thread()
        self._inspection.receive_thread_finished(self.sender())

    @Slot(object)
    def _manual_terminal_received(self, envelope: object) -> None:
        self._assert_gui_thread()
        self._manual.receive_terminal(envelope)

    @Slot()
    def _manual_thread_finished(self) -> None:
        self._assert_gui_thread()
        self._manual.receive_thread_finished(self.sender())

    def _owned_worker_released(self) -> None:
        self._assert_gui_thread()
        self._maybe_emit_shutdown_ready()

    def _manual_announcement(self, route: Route, text: str, revision: int) -> None:
        self._assert_gui_thread()
        signal = {
            Route.MEMORY: self.memoryAnnouncement,
            Route.PROJECTS: self.projectsAnnouncement,
            Route.VALIDATION_HISTORY: self.validationHistoryAnnouncement,
            Route.SETTINGS: self.settingsAnnouncement,
        }[route]
        signal.emit(text, revision)

    def _maybe_emit_shutdown_ready(self) -> None:
        if (
            not self._shutdown_requested
            or self._shutdown_ready_emitted
            or self._controller.state is not ShellState.SHUTDOWN
            or self._inspection.state is not ContextInspectionPageState.SHUTDOWN
            or self._manual.memory_state is not MemoryPageState.SHUTDOWN
            or self._manual.projects_state is not ProjectsPageState.SHUTDOWN
            or self._manual.validation_state is not ValidationHistoryPageState.SHUTDOWN
            or self._manual.settings_state is not SettingsPageState.SHUTDOWN
            or self._controller.active_execution_id is not None
            or self._inspection.active_generation is not None
            or self._manual.active_operation_id is not None
        ):
            return
        self._shutdown_ready_emitted = True
        self.shutdownReady.emit()

    def _current_conversation_terminal(self) -> None:
        conversation_id = self._controller._conversation_id
        if isinstance(conversation_id, DomainId):
            self._inspection.current_conversation_terminal(conversation_id)
            self._manual.current_conversation_terminal(conversation_id)

    def _current_conversation_changed(self, conversation_id: DomainId) -> bool:
        self._assert_gui_thread()
        if not self._controller.current_conversation_changed(conversation_id):
            return False
        changed = self._inspection.current_conversation_changed(conversation_id)
        if not changed:
            raise RuntimeError("Shell conversation owners became inconsistent.")
        self._manual.current_conversation_changed(conversation_id)
        return True

    def _current_project_changed(self) -> bool:
        self._assert_gui_thread()
        return self._inspection.current_project_changed()

    def _apply_context_panel_visible(self, value: bool) -> None:
        self._assert_gui_thread()
        if not isinstance(value, bool):
            raise TypeError("Context-panel visibility must be boolean.")
        self._context_panel_visible = value
        if not value and self._inspection.route is Route.CONTEXT_INSPECTION:
            if not self._inspection.navigate_to_chat():
                raise RuntimeError("Context inspection could not navigate away safely.")
            self._manual.navigate_away(Route.CHAT)
        self.changed.emit()

    def dispose(self) -> None:
        self._assert_gui_thread()
        self._controller.dispose()
        self._inspection.dispose()
        self._manual.dispose()


__all__ = ["ShellFacade"]
