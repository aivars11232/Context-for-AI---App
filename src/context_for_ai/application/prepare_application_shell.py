"""Pre-QML recovery preflight and deterministic shell conversation selection."""

from __future__ import annotations

from context_for_ai.application.contracts import (
    PrepareApplicationShellRequest,
    PrepareApplicationShellResult,
    RecoveryRequiredResult,
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
    ShellReadyResult,
)
from context_for_ai.domain.entities import Conversation, ConversationState
from context_for_ai.domain.enums import ProjectStatus
from context_for_ai.domain.errors import DomainError
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.repositories import (
    ConversationRepository,
    ConversationStateRepository,
    ProcessingRunRepository,
    ProjectRepository,
    SettingsRepository,
)
from context_for_ai.domain.ports.system import Clock, IdGenerator, TransactionBoundary
from context_for_ai.domain.value_objects import DomainId


_LAST_SELECTED_CONVERSATION_KEY = "ui.last_selected_conversation_id"


class PrepareApplicationShellService:
    """Prepare one startup selection without classifying or resuming recovery."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        conversation_states: ConversationStateRepository,
        processing_runs: ProcessingRunRepository,
        settings: SettingsRepository,
        transactions: TransactionBoundary,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._projects = projects
        self._conversations = conversations
        self._conversation_states = conversation_states
        self._processing_runs = processing_runs
        self._settings = settings
        self._transactions = transactions
        self._clock = clock
        self._id_generator = id_generator

    def execute(
        self,
        request: PrepareApplicationShellRequest,
    ) -> PrepareApplicationShellResult:
        if not isinstance(request, PrepareApplicationShellRequest):
            raise TypeError(
                "PrepareApplicationShellService requires its empty request type."
            )

        try:
            active_run = self._processing_runs.get_non_terminal()
        except PersistenceError:
            return ShellPreparationFailureResult(
                ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
            )

        if active_run is not None:
            return RecoveryRequiredResult(
                processing_run_id=active_run.id,
                conversation_id=active_run.conversation_id,
            )

        try:
            selected = self._preferred_conversation()
            if selected is not None:
                return ShellReadyResult(
                    conversation_id=selected.id,
                    initial_conversation_created=False,
                )
            selected = self._latest_conversation()
            if selected is not None:
                self._require_state(selected.id)
                return ShellReadyResult(
                    conversation_id=selected.id,
                    initial_conversation_created=False,
                )
            return self._create_initial_conversation()
        except PersistenceError:
            return ShellPreparationFailureResult(
                ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
            )

    def _preferred_conversation(self) -> Conversation | None:
        setting = self._settings.get(_LAST_SELECTED_CONVERSATION_KEY)
        if setting is None or setting.value is None:
            return None
        if not isinstance(setting.value, str):
            raise PersistenceError("Stored conversation preference is invalid.")
        try:
            conversation_id = DomainId(setting.value)
        except DomainError as error:
            raise PersistenceError("Stored conversation preference is invalid.") from error
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return None
        self._require_state(conversation.id)
        return conversation

    def _latest_conversation(self) -> Conversation | None:
        conversations = list(self._conversations.list_for_project(None))
        for status in (ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED):
            for project in self._projects.list_by_status(status):
                conversations.extend(
                    self._conversations.list_for_project(project.id)
                )
        if not conversations:
            return None
        latest_time = max(conversation.updated_at for conversation in conversations)
        return min(
            (
                conversation
                for conversation in conversations
                if conversation.updated_at == latest_time
            ),
            key=lambda conversation: str(conversation.id),
        )

    def _require_state(self, conversation_id: DomainId) -> ConversationState:
        state = self._conversation_states.get(conversation_id)
        if state is None or state.conversation_id != conversation_id:
            raise PersistenceError("Conversation state does not exist.")
        return state

    def _create_initial_conversation(self) -> ShellReadyResult:
        conversation_id = self._id_generator.new_id()
        created_at = self._clock.now()
        conversation = Conversation(
            id=conversation_id,
            project_id=None,
            title=None,
            created_at=created_at,
            updated_at=created_at,
        )
        state = ConversationState(
            conversation_id=conversation_id,
            active_topic_id=None,
            active_task_id=None,
            previous_task_id=None,
            expected_output_type=None,
            topic_stack=(),
            version=0,
            updated_at=created_at,
        )
        with self._transactions.transaction():
            self._conversations.add(conversation)
            self._conversation_states.add(state)
        return ShellReadyResult(
            conversation_id=conversation_id,
            initial_conversation_created=True,
        )


__all__ = ["PrepareApplicationShellService"]
