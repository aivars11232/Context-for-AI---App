"""One GUI-owned QML facade with one finite foreground QThread at a time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, Qt, Signal, Slot

from context_for_ai.application import (
    IdempotencyKeyFactory,
    ProcessUserMessageRequest,
    RecoverProcessingRunRequest,
    RecoveryRequiredResult,
    ShellApplicationScopeFactory,
    ShellReadyResult,
)
from context_for_ai.ui.presentation import (
    ExecutionKind,
    ForegroundExecutionFailureView,
    ForegroundTerminalEnvelope,
    MonotonicCancellationToken,
    ShellState,
    TerminalPresentationView,
    contained_foreground_result,
    terminal_presentation_view,
)


_PROGRESS_LABELS = {
    ShellState.STARTUP: "Starting…",
    ShellState.RECOVERY: "Recovering an interrupted request…",
    ShellState.PENDING: "Processing…",
    ShellState.CANCELLATION_REQUESTED: "Cancelling…",
}


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
        self._shutdown_ready_emitted = False
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
            self._emit_shutdown_ready()

    def request_shutdown(self) -> None:
        if self._disposed or self._state is ShellState.SHUTDOWN:
            return
        self._state = ShellState.SHUTDOWN
        self._submission_permitted = False
        self._clear_terminal(ShellState.SHUTDOWN)
        if self._active is not None:
            self._active.token.request_cancellation()
        self._notify()
        if self._active is None:
            self._emit_shutdown_ready()

    def _emit_shutdown_ready(self) -> None:
        if self._shutdown_ready_emitted:
            return
        self._shutdown_ready_emitted = True
        self._owner.shutdownReady.emit()

    def dispose(self) -> None:
        self._disposed = True
        if self._active is not None:
            self._active.token.request_cancellation()
        self._active = None


class ShellFacade(QObject):
    """The sole GUI-thread-owned QObject and primitive QML presentation surface."""

    changed = Signal()
    shutdownReady = Signal()

    def __init__(
        self,
        scope_factory: ShellApplicationScopeFactory,
        idempotency_keys: IdempotencyKeyFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = _ForegroundRunController(
            owner=self,
            scope_factory=scope_factory,
            idempotency_keys=idempotency_keys,
        )

    def _assert_gui_thread(self) -> None:
        if QThread.currentThread() is not self.thread():
            raise RuntimeError("ShellFacade may be used only on its GUI thread.")

    @Property(str, notify=changed)
    def route(self) -> str:
        return "CHAT"

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
        return self._controller.progress_visible

    @Property(str, notify=changed)
    def progress_label(self) -> str:
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
        self._controller.apply_preparation(result)

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
        self._controller.request_shutdown()

    @Slot(object)
    def _terminal_received(self, envelope: object) -> None:
        self._assert_gui_thread()
        self._controller.receive_terminal(envelope)

    @Slot()
    def _thread_finished(self) -> None:
        self._assert_gui_thread()
        self._controller.receive_thread_finished(self.sender())

    def dispose(self) -> None:
        self._assert_gui_thread()
        self._controller.dispose()


__all__ = ["ShellFacade"]
