"""Safe TASK-0017 memory inspection and explicit mutation adapters."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from context_for_ai.application.contracts import (
    CanonicalLabelView,
    CreateMemory,
    CreateMemoryInput,
    CreateMemoryPresentationRequest,
    EditMemory,
    EditMemoryInput,
    EditMemoryPresentationRequest,
    InspectMemoriesRequest,
    InspectMemoriesResult,
    InspectionScoreView,
    ListMemories,
    ListMemoriesInput,
    MemoryDetailsView,
    MemoryDuplicateCandidateView,
    MemoryDuplicateDecision,
    MemoryDuplicateGuidanceResult,
    MemoryField,
    MemoryFieldError,
    MemoryInspectionCollectionView,
    MemoryInspectionEmptyResult,
    MemoryInspectionItemView,
    MemoryInspectionLoadFailureResult,
    MemoryInspectionReadyResult,
    MemoryMutationFailureResult,
    MemoryMutationOperation,
    MemoryMutationRejectedResult,
    MemoryMutationResult,
    MemoryMutationStaleResult,
    MemoryMutationSucceededResult,
    MemoryMutationValidationFailureResult,
    MemoryOwnerKind,
    MemoryOwnerView,
    MemoryRevisionView,
    MemorySourceView,
    MemorySummaryView,
    SoftDeleteMemory,
    SoftDeleteMemoryInput,
    SoftDeleteMemoryPresentationRequest,
)
from context_for_ai.application.manual_settings import ReadOnlySnapshotBoundary
from context_for_ai.context_engine import normalize_retrieval_content
from context_for_ai.domain.entities import Conversation, Memory, Project
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    PipelineStage,
    ProjectStatus,
)
from context_for_ai.domain.errors import DomainError, LifecycleInvariantError
from context_for_ai.domain.policies import memory_effective_status
from context_for_ai.domain.ports.configuration import ConfigurationSnapshot
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.ports.repositories import (
    ConversationRepository,
    MemoryRepository,
    ProjectRepository,
)
from context_for_ai.domain.ports.system import (
    Clock,
    TraceEvent,
    TraceLogger,
    TransactionBoundary,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    UnitScore,
    canonical_decimal_string,
    ensure_utc,
    parse_utc_timestamp,
)


def _label(value: object) -> CanonicalLabelView:
    code = value.value if hasattr(value, "value") else str(value)
    words = code.split("_")
    rendered = " ".join(word.lower() for word in words)
    return CanonicalLabelView(code, rendered[0].upper() + rendered[1:])


def _score(value: UnitScore | Decimal | str) -> InspectionScoreView:
    decimal = value.value if isinstance(value, UnitScore) else Decimal(value)
    canonical = canonical_decimal_string(decimal)
    displayed = format(
        decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
        ".2f",
    )
    return InspectionScoreView(canonical, displayed)


def _utc_text(value: object) -> str:
    normalized = ensure_utc(value)  # type: ignore[arg-type]
    return normalized.strftime("%Y-%m-%d %H:%M:%S UTC")


def _optional_time_text(value: object, empty_text: str) -> str:
    return empty_text if value is None else _utc_text(value)


def _required_conversation(
    conversations: ConversationRepository,
    conversation_id: DomainId,
) -> Conversation:
    conversation = conversations.get(conversation_id)
    if conversation is None:
        raise PersistenceError("Memory conversation is unavailable.")
    return conversation


def _required_project(
    projects: ProjectRepository,
    project_id: DomainId,
) -> Project:
    project = projects.get(project_id)
    if project is None:
        raise PersistenceError("Memory project is unavailable.")
    return project


def _owner_view(
    memory: Memory,
    *,
    conversations: ConversationRepository,
    projects: ProjectRepository,
) -> MemoryOwnerView:
    if memory.scope is MemoryScope.CONVERSATION:
        if memory.conversation_id is None:
            raise PersistenceError("Conversation memory owner is unavailable.")
        conversation = _required_conversation(conversations, memory.conversation_id)
        title = conversation.title or "Untitled conversation"
        return MemoryOwnerView(
            MemoryOwnerKind.CONVERSATION,
            f"Conversation: {title}",
            None,
        )
    if memory.scope is MemoryScope.PROJECT:
        if memory.project_id is None:
            raise PersistenceError("Project memory owner is unavailable.")
        project = _required_project(projects, memory.project_id)
        return MemoryOwnerView(
            MemoryOwnerKind.PROJECT,
            f"Project: {project.name}",
            _label(project.status),
        )
    if memory.scope is not MemoryScope.GLOBAL or (
        memory.conversation_id is not None or memory.project_id is not None
    ):
        raise PersistenceError("Global memory owner is inconsistent.")
    return MemoryOwnerView(
        MemoryOwnerKind.GLOBAL,
        "All conversations and projects",
        None,
    )


def _metadata_text(metadata: object, key: str) -> str:
    value = metadata[key]  # type: ignore[index]
    if not isinstance(value, str):
        raise PersistenceError("Memory revision metadata is invalid.")
    return value


def _metadata_texts(metadata: object, key: str) -> tuple[str, ...]:
    value = metadata[key]  # type: ignore[index]
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise PersistenceError("Memory revision metadata is invalid.")
    return value


def _memory_item(
    record: MemoryRecord,
    *,
    evaluated_at: object,
    ordinal: int,
    conversations: ConversationRepository,
    projects: ProjectRepository,
) -> MemoryInspectionItemView:
    memory = record.memory
    normalized_evaluated_at = ensure_utc(evaluated_at)  # type: ignore[arg-type]
    effective = memory_effective_status(memory, normalized_evaluated_at)
    owner = _owner_view(
        memory,
        conversations=conversations,
        projects=projects,
    )
    source_ordinals = {
        str(source.id): index for index, source in enumerate(record.sources, start=1)
    }
    sources = tuple(
        MemorySourceView(
            ordinal=index,
            kind=_label(source.source_kind),
            description=source.description,
            source_message="Not applicable.",
            created_at_text=_utc_text(source.created_at),
        )
        for index, source in enumerate(record.sources, start=1)
    )
    revisions: list[MemoryRevisionView] = []
    for revision in record.revisions:
        metadata = revision.metadata
        source_id = _metadata_text(metadata, "source_id")
        try:
            source_ordinal = source_ordinals[source_id]
        except KeyError as error:
            raise PersistenceError(
                "Memory revision source is unavailable."
            ) from error
        expires_at_raw = metadata["expires_at"]
        deleted_at_raw = metadata["deleted_at"]
        expires_at = (
            None
            if expires_at_raw is None
            else parse_utc_timestamp(_metadata_text(metadata, "expires_at"))
        )
        deleted_at = (
            None
            if deleted_at_raw is None
            else parse_utc_timestamp(_metadata_text(metadata, "deleted_at"))
        )
        updated_at = parse_utc_timestamp(_metadata_text(metadata, "updated_at"))
        revisions.append(
            MemoryRevisionView(
                revision_number=revision.revision_number,
                operation=_label(revision.operation),
                source_ordinal=source_ordinal,
                content_snapshot=revision.content_snapshot,
                keywords=_metadata_texts(metadata, "keywords"),
                topic_terms=_metadata_texts(metadata, "topic_terms"),
                importance=_score(_metadata_text(metadata, "importance")),
                confidence=_score(_metadata_text(metadata, "confidence")),
                expires_at_text=_optional_time_text(
                    expires_at, "Does not expire."
                ),
                stored_status=_label(
                    MemoryStatus(_metadata_text(metadata, "status"))
                ),
                updated_at_text=_utc_text(updated_at),
                deleted_at_text=_optional_time_text(deleted_at, "Not deleted."),
                performed_by=_label(revision.performed_by),
                performed_at_text=_utc_text(revision.created_at),
            )
        )
    summary = MemorySummaryView(
        content=memory.content,
        type=_label(memory.memory_type),
        scope=_label(memory.scope),
        owner=owner,
        stored_status=_label(memory.status),
        effective_status=_label(effective),
        updated_at_text=_utc_text(memory.updated_at),
    )
    details = MemoryDetailsView(
        content=memory.content,
        keywords=memory.keywords,
        topic_terms=memory.topic_terms,
        importance=_score(memory.importance),
        confidence=_score(memory.confidence),
        expires_at_text=_optional_time_text(memory.expires_at, "Does not expire."),
        created_at_text=_utc_text(memory.created_at),
        updated_at_text=_utc_text(memory.updated_at),
        deleted_at_text=_optional_time_text(memory.deleted_at, "Not deleted."),
        stored_status=_label(memory.status),
        effective_status=_label(effective),
        evaluated_at_text=_utc_text(normalized_evaluated_at),
        sources=sources,
        revisions=tuple(revisions),
    )
    return MemoryInspectionItemView(
        ordinal,
        summary,
        details,
        private_memory_id=memory.id,
    )


def _memory_field_error(field: MemoryField) -> MemoryFieldError:
    messages = {
        MemoryField.TYPE: "Choose a valid memory type.",
        MemoryField.SCOPE: "Choose a valid memory scope.",
        MemoryField.OWNER: "An active project is required for project memory.",
        MemoryField.IMPORTANCE: "Importance must be between 0 and 1.",
        MemoryField.CONFIDENCE: "Confidence must be between 0 and 1.",
        MemoryField.EXPIRY: "Expiry must be a valid UTC date and time or empty.",
        MemoryField.SOURCE_DESCRIPTION: "Describe why this memory is being changed.",
    }
    return MemoryFieldError(field, messages[field])


def _validated_score(value: object) -> UnitScore | None:
    if not isinstance(value, Decimal) or not value.is_finite():
        return None
    try:
        return UnitScore(value)
    except DomainError:
        return None


def _validated_expiry(value: object) -> object:
    if value is None:
        return None
    try:
        return ensure_utc(value)  # type: ignore[arg-type]
    except DomainError:
        return _INVALID


_INVALID = object()


def _common_validation(
    *,
    importance: object,
    confidence: object,
    expires_at: object,
    source_description: object,
) -> tuple[
    tuple[MemoryFieldError, ...],
    UnitScore | None,
    UnitScore | None,
    object,
]:
    errors: list[MemoryFieldError] = []
    importance_score = _validated_score(importance)
    confidence_score = _validated_score(confidence)
    expiry = _validated_expiry(expires_at)
    if importance_score is None:
        errors.append(_memory_field_error(MemoryField.IMPORTANCE))
    if confidence_score is None:
        errors.append(_memory_field_error(MemoryField.CONFIDENCE))
    if expiry is _INVALID:
        errors.append(_memory_field_error(MemoryField.EXPIRY))
    if not isinstance(source_description, str) or not source_description.strip():
        errors.append(_memory_field_error(MemoryField.SOURCE_DESCRIPTION))
    return tuple(errors), importance_score, confidence_score, expiry


class InspectMemoriesService:
    """Return one closed stored-status memory snapshot with one query clock."""

    def __init__(
        self,
        *,
        list_memories: ListMemories,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        snapshots: ReadOnlySnapshotBoundary,
    ) -> None:
        self._list_memories = list_memories
        self._conversations = conversations
        self._projects = projects
        self._snapshots = snapshots

    def execute(self, request: InspectMemoriesRequest) -> InspectMemoriesResult:
        if not isinstance(request, InspectMemoriesRequest):
            raise TypeError("InspectMemoriesService requires its request type.")
        if not isinstance(request.stored_status, MemoryStatus):
            return MemoryInspectionLoadFailureResult()
        try:
            with self._snapshots.snapshot():
                output = self._list_memories.execute(
                    ListMemoriesInput(request.stored_status)
                )
                evaluated_at_text = _utc_text(output.evaluated_at)
                if not output.records:
                    return MemoryInspectionEmptyResult(
                        request.stored_status,
                        evaluated_at_text,
                    )
                items = tuple(
                    _memory_item(
                        memory_output.record,
                        evaluated_at=output.evaluated_at,
                        ordinal=index,
                        conversations=self._conversations,
                        projects=self._projects,
                    )
                    for index, memory_output in enumerate(output.records, start=1)
                )
                selected_ordinal = next(
                    (
                        index
                        for index, memory_output in enumerate(
                            output.records, start=1
                        )
                        if memory_output.record.memory.id
                        == request.selected_memory_id
                    ),
                    None,
                )
                return MemoryInspectionReadyResult(
                    MemoryInspectionCollectionView(
                        stored_status_filter=request.stored_status,
                        evaluated_at_text=evaluated_at_text,
                        items=items,
                        selected_ordinal=selected_ordinal,
                    )
                )
        except (DomainError, PersistenceError, InvalidOperation, KeyError, TypeError):
            return MemoryInspectionLoadFailureResult()


class _MutationSupport:
    def __init__(
        self,
        *,
        memories: MemoryRepository,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        transactions: TransactionBoundary,
        trace_logger: TraceLogger,
        configuration: ConfigurationSnapshot,
    ) -> None:
        self._memories = memories
        self._conversations = conversations
        self._projects = projects
        self._transactions = transactions
        self._trace_logger = trace_logger
        self._configuration_fingerprint = configuration.configuration_fingerprint

    def _item(self, record: MemoryRecord, evaluated_at: object) -> MemoryInspectionItemView:
        return _memory_item(
            record,
            evaluated_at=evaluated_at,
            ordinal=1,
            conversations=self._conversations,
            projects=self._projects,
        )

    def _trace(self, *, event_name: str, record: MemoryRecord) -> None:
        try:
            self._trace_logger.emit(
                TraceEvent(
                    timestamp=record.memory.updated_at,
                    level="INFO",
                    event_name=event_name,
                    stage=PipelineStage.MEMORY,
                    configuration_fingerprint=self._configuration_fingerprint,
                    memory_id=record.memory.id,
                    memory_revision_id=record.revisions[-1].id,
                )
            )
        except Exception:
            return


class CreateMemoryPresentationService(_MutationSupport):
    """Validate ownership and duplicates around canonical memory creation."""

    def __init__(
        self,
        *,
        create_memory: CreateMemory,
        clock: Clock,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._create_memory = create_memory
        self._clock = clock

    def execute(
        self,
        request: CreateMemoryPresentationRequest,
    ) -> MemoryMutationResult:
        if not isinstance(request, CreateMemoryPresentationRequest):
            raise TypeError(
                "CreateMemoryPresentationService requires its request type."
            )
        errors: list[MemoryFieldError] = []
        if not isinstance(request.memory_type, MemoryType):
            errors.append(_memory_field_error(MemoryField.TYPE))
        if not isinstance(request.scope, MemoryScope):
            errors.append(_memory_field_error(MemoryField.SCOPE))
        common, importance, confidence, expiry = _common_validation(
            importance=request.importance,
            confidence=request.confidence,
            expires_at=request.expires_at,
            source_description=request.source_description,
        )
        errors.extend(common)
        if errors:
            return MemoryMutationValidationFailureResult(tuple(errors))
        if (
            not isinstance(request.content, str)
            or any(not isinstance(value, str) for value in request.keywords)
            or any(not isinstance(value, str) for value in request.topic_terms)
            or not isinstance(request.duplicate_decision, MemoryDuplicateDecision)
            or importance is None
            or confidence is None
            or expiry is _INVALID
        ):
            return MemoryMutationFailureResult(
                "Memory could not be created safely."
            )

        try:
            with self._transactions.transaction():
                conversation = _required_conversation(
                    self._conversations,
                    request.conversation_id,
                )
                conversation_id: DomainId | None = None
                project_id: DomainId | None = None
                if request.scope is MemoryScope.CONVERSATION:
                    conversation_id = conversation.id
                elif request.scope is MemoryScope.PROJECT:
                    if conversation.project_id is None:
                        return MemoryMutationValidationFailureResult(
                            (_memory_field_error(MemoryField.OWNER),)
                        )
                    project = self._projects.get(conversation.project_id)
                    if project is None or project.status is not ProjectStatus.ACTIVE:
                        return MemoryMutationValidationFailureResult(
                            (_memory_field_error(MemoryField.OWNER),)
                        )
                    project_id = project.id

                normalized = normalize_retrieval_content(request.content)
                candidates = tuple(
                    record
                    for record in self._memories.list_by_status(MemoryStatus.ACTIVE)
                    if _same_owner(
                        record.memory,
                        scope=request.scope,
                        conversation_id=conversation_id,
                        project_id=project_id,
                    )
                    and normalize_retrieval_content(record.memory.content)
                    == normalized
                )
                if (
                    request.duplicate_decision is MemoryDuplicateDecision.CHECK
                    and candidates
                ):
                    evaluated_at = ensure_utc(self._clock.now())
                    return MemoryDuplicateGuidanceResult(
                        tuple(
                            MemoryDuplicateCandidateView(
                                ordinal=index,
                                content=record.memory.content,
                                scope=_label(record.memory.scope),
                                owner_display_text=_owner_view(
                                    record.memory,
                                    conversations=self._conversations,
                                    projects=self._projects,
                                ).display_text,
                                effective_status=_label(
                                    memory_effective_status(
                                        record.memory, evaluated_at
                                    )
                                ),
                                updated_at_text=_utc_text(
                                    record.memory.updated_at
                                ),
                            )
                            for index, record in enumerate(candidates, start=1)
                        )
                    )

                output = self._create_memory.execute(
                    CreateMemoryInput(
                        conversation_id=conversation_id,
                        project_id=project_id,
                        memory_type=request.memory_type,
                        scope=request.scope,
                        content=request.content,
                        keywords=request.keywords,
                        topic_terms=request.topic_terms,
                        importance=importance,
                        confidence=confidence,
                        expires_at=expiry,  # type: ignore[arg-type]
                        source_description=request.source_description,
                    )
                )
                affected = self._item(output.record, output.evaluated_at)
            self._trace(event_name="memory_created", record=output.record)
            return MemoryMutationSucceededResult(
                MemoryMutationOperation.CREATE,
                affected,
                output.record.revisions[-1].revision_number,
            )
        except (DomainError, PersistenceError, InvalidOperation, KeyError, TypeError):
            return MemoryMutationFailureResult(
                "Memory could not be created safely."
            )


def _same_owner(
    memory: Memory,
    *,
    scope: MemoryScope,
    conversation_id: DomainId | None,
    project_id: DomainId | None,
) -> bool:
    if memory.scope is not scope:
        return False
    if scope is MemoryScope.CONVERSATION:
        return memory.conversation_id == conversation_id
    if scope is MemoryScope.PROJECT:
        return memory.project_id == project_id
    return memory.conversation_id is None and memory.project_id is None


class EditMemoryPresentationService(_MutationSupport):
    """Apply one guarded canonical edit without automatic retry."""

    def __init__(self, *, edit_memory: EditMemory, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._edit_memory = edit_memory

    def execute(
        self,
        request: EditMemoryPresentationRequest,
    ) -> MemoryMutationResult:
        if not isinstance(request, EditMemoryPresentationRequest):
            raise TypeError("EditMemoryPresentationService requires its request type.")
        errors, importance, confidence, expiry = _common_validation(
            importance=request.importance,
            confidence=request.confidence,
            expires_at=request.expires_at,
            source_description=request.source_description,
        )
        if errors:
            return MemoryMutationValidationFailureResult(errors)
        if (
            not isinstance(request.content, str)
            or any(not isinstance(value, str) for value in request.keywords)
            or any(not isinstance(value, str) for value in request.topic_terms)
            or importance is None
            or confidence is None
            or expiry is _INVALID
        ):
            return MemoryMutationFailureResult(
                "Memory could not be updated safely."
            )
        try:
            with self._transactions.transaction():
                current = self._memories.get(request.memory_id)
                if current is None:
                    return MemoryMutationRejectedResult("MEMORY_NOT_FOUND")
                if current.memory.status is MemoryStatus.DELETED:
                    return MemoryMutationRejectedResult("MEMORY_DELETED")
                if (
                    current.revisions[-1].revision_number
                    != request.expected_revision_number
                ):
                    return MemoryMutationStaleResult()
                output = self._edit_memory.execute(
                    EditMemoryInput(
                        memory_id=request.memory_id,
                        content=request.content,
                        keywords=request.keywords,
                        topic_terms=request.topic_terms,
                        importance=importance,
                        confidence=confidence,
                        expires_at=expiry,  # type: ignore[arg-type]
                        source_description=request.source_description,
                    )
                )
                affected = self._item(output.record, output.evaluated_at)
            self._trace(event_name="memory_edited", record=output.record)
            return MemoryMutationSucceededResult(
                MemoryMutationOperation.EDIT,
                affected,
                output.record.revisions[-1].revision_number,
            )
        except (DomainError, PersistenceError, InvalidOperation, KeyError, TypeError):
            return MemoryMutationFailureResult(
                "Memory could not be updated safely."
            )


class SoftDeleteMemoryPresentationService(_MutationSupport):
    """Apply one guarded canonical soft delete without retry or restore."""

    def __init__(
        self,
        *,
        soft_delete_memory: SoftDeleteMemory,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._soft_delete_memory = soft_delete_memory

    def execute(
        self,
        request: SoftDeleteMemoryPresentationRequest,
    ) -> MemoryMutationResult:
        if not isinstance(request, SoftDeleteMemoryPresentationRequest):
            raise TypeError(
                "SoftDeleteMemoryPresentationService requires its request type."
            )
        if not isinstance(request.source_description, str) or not request.source_description.strip():
            return MemoryMutationValidationFailureResult(
                (_memory_field_error(MemoryField.SOURCE_DESCRIPTION),)
            )
        try:
            with self._transactions.transaction():
                current = self._memories.get(request.memory_id)
                if current is None:
                    return MemoryMutationRejectedResult("MEMORY_NOT_FOUND")
                if current.memory.status is MemoryStatus.DELETED:
                    return MemoryMutationRejectedResult("MEMORY_DELETED")
                if (
                    current.revisions[-1].revision_number
                    != request.expected_revision_number
                ):
                    return MemoryMutationStaleResult()
                output = self._soft_delete_memory.execute(
                    SoftDeleteMemoryInput(
                        request.memory_id,
                        request.source_description,
                    )
                )
                affected = self._item(output.record, output.evaluated_at)
            self._trace(event_name="memory_soft_deleted", record=output.record)
            return MemoryMutationSucceededResult(
                MemoryMutationOperation.SOFT_DELETE,
                affected,
                output.record.revisions[-1].revision_number,
            )
        except (DomainError, PersistenceError, InvalidOperation, KeyError, TypeError):
            return MemoryMutationFailureResult(
                "Memory could not be soft-deleted safely."
            )


__all__ = [
    "CreateMemoryPresentationService",
    "EditMemoryPresentationService",
    "InspectMemoriesService",
    "SoftDeleteMemoryPresentationService",
]
