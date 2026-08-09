"""Closed TASK-0017 presentation preferences and configuration inspection."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from context_for_ai.application.contracts import (
    ConfigurationCategoryName,
    ConfigurationCategoryView,
    ConfigurationFieldView,
    ConfigurationInspectionView,
    ConfigurationOriginView,
    InitialUiPreferences,
    InspectManualSettingsRequest,
    InspectManualSettingsResult,
    ManualSettingKey,
    ManualSettingsLoadFailureResult,
    ManualSettingsMutationFailureResult,
    ManualSettingsReadyResult,
    ManualSettingsUpdateSucceededResult,
    ManualSettingsValidationFailureResult,
    ManualSettingsView,
    SettingUpdate,
    SettingsField,
    SettingsFieldError,
    UiTheme,
    UpdateManualSettingsRequest,
    UpdateManualSettingsResult,
)
from context_for_ai.domain.errors import DomainError, LifecycleInvariantError
from context_for_ai.domain.ports.configuration import (
    ConfigurationOrigin,
    ConfigurationSnapshot,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.repositories import SettingsRepository
from context_for_ai.domain.ports.system import Clock, TransactionBoundary
from context_for_ai.domain.value_objects import DomainId


_THEME_KEY = "ui.theme"
_CONTEXT_VISIBLE_KEY = "ui.context_panel_visible"
_LAST_CONVERSATION_KEY = "ui.last_selected_conversation_id"
_PERMITTED_KEYS = frozenset(
    {_THEME_KEY, _CONTEXT_VISIBLE_KEY, _LAST_CONVERSATION_KEY}
)
_ORIGIN_LABELS = {
    ConfigurationOrigin.PROCESS_OVERRIDE: "Process override",
    ConfigurationOrigin.LOCAL_YAML: "Local YAML",
    ConfigurationOrigin.DOCUMENTED_DEFAULT: "Documented default",
    ConfigurationOrigin.FIXED_MVP: "Fixed MVP rule",
}


class ReadOnlySnapshotBoundary(Protocol):
    """Open one connection-local read-only snapshot."""

    def snapshot(self) -> AbstractContextManager[None]: ...


def _validated_preferences(
    settings: SettingsRepository,
) -> tuple[UiTheme, bool, DomainId | None]:
    rows = settings.list_all()
    values: dict[str, object] = {}
    for row in rows:
        if row.key not in _PERMITTED_KEYS or row.key in values:
            raise PersistenceError("Stored presentation settings are invalid.")
        values[row.key] = row.value

    raw_theme = values.get(_THEME_KEY, UiTheme.SYSTEM.value)
    try:
        theme = UiTheme(raw_theme)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise PersistenceError("Stored presentation settings are invalid.") from error

    context_visible = values.get(_CONTEXT_VISIBLE_KEY, True)
    if not isinstance(context_visible, bool):
        raise PersistenceError("Stored presentation settings are invalid.")

    raw_conversation = values.get(_LAST_CONVERSATION_KEY)
    if raw_conversation is None:
        conversation_id = None
    elif isinstance(raw_conversation, str):
        try:
            conversation_id = DomainId(raw_conversation)
        except DomainError as error:
            raise PersistenceError(
                "Stored presentation settings are invalid."
            ) from error
    else:
        raise PersistenceError("Stored presentation settings are invalid.")
    return theme, context_visible, conversation_id


def _origin_view(origin: ConfigurationOrigin) -> ConfigurationOriginView:
    return ConfigurationOriginView(origin, _ORIGIN_LABELS[origin])


def _configuration_view(
    configuration: ConfigurationSnapshot,
) -> ConfigurationInspectionView:
    origins = {
        item.field_path: item.origin for item in configuration.scalar_origins
    }

    def sourced(field_path: str) -> ConfigurationOriginView:
        try:
            return _origin_view(origins[field_path])
        except (KeyError, TypeError, ValueError) as error:
            raise LifecycleInvariantError(
                "Required configuration origin is unavailable."
            ) from error

    fixed = _origin_view(ConfigurationOrigin.FIXED_MVP)

    def field(
        ordinal: int,
        label: str,
        value_text: str,
        origin: ConfigurationOriginView,
    ) -> ConfigurationFieldView:
        return ConfigurationFieldView(ordinal, label, value_text, origin)

    categories = (
        ConfigurationCategoryView(
            1,
            ConfigurationCategoryName.APPLICATION,
            (field(1, "Foreground processing limit", "1", fixed),),
        ),
        ConfigurationCategoryView(
            2,
            ConfigurationCategoryName.MODEL,
            (
                field(1, "Provider", "Ollama", fixed),
                field(
                    2,
                    "Execution locality",
                    "Direct numeric loopback only",
                    fixed,
                ),
                field(3, "Model routing", "Disabled", fixed),
            ),
        ),
        ConfigurationCategoryView(
            3,
            ConfigurationCategoryName.STORAGE,
            (
                field(1, "Database", "SQLite", fixed),
                field(
                    2,
                    "Data location",
                    "Local path (value hidden)",
                    sourced("app.data_directory"),
                ),
            ),
        ),
        ConfigurationCategoryView(
            4,
            ConfigurationCategoryName.MEMORY,
            (
                field(1, "Manual create", "Enabled", fixed),
                field(2, "Manual edit", "Enabled", fixed),
                field(3, "Manual soft-delete", "Enabled", fixed),
                field(4, "Automatic mutation", "Disabled", fixed),
            ),
        ),
        ConfigurationCategoryView(
            5,
            ConfigurationCategoryName.VALIDATION,
            (
                field(
                    1,
                    "Maximum automatic revisions",
                    str(configuration.validation.max_revisions),
                    sourced("validation.max_revisions"),
                ),
            ),
        ),
        ConfigurationCategoryView(
            6,
            ConfigurationCategoryName.LOGGING,
            (
                field(
                    1,
                    "Level",
                    configuration.logging.level.title(),
                    sourced("logging.level"),
                ),
                field(
                    2,
                    "Retention",
                    f"{configuration.logging.retention_days} days",
                    sourced("logging.retention_days"),
                ),
                field(3, "Content logging", "Disabled", fixed),
                field(
                    4,
                    "Log location",
                    "Local path (value hidden)",
                    sourced("logging.directory"),
                ),
            ),
        ),
        ConfigurationCategoryView(
            7,
            ConfigurationCategoryName.SECURITY,
            (
                field(1, "Cloud providers", "Disabled", fixed),
                field(2, "Credentials and API keys", "Unsupported", fixed),
                field(3, "Proxy and provider fallback", "Disabled", fixed),
                field(
                    4,
                    "Ollama cloud-disable attestation",
                    "Required before each prompt",
                    fixed,
                ),
            ),
        ),
    )
    return ConfigurationInspectionView(
        categories=categories,
        fingerprint=configuration.configuration_fingerprint,
    )


class LoadInitialUiPreferencesService:
    """Validate all stored settings and resolve startup defaults without writes."""

    def __init__(
        self,
        *,
        settings: SettingsRepository,
        snapshots: ReadOnlySnapshotBoundary,
    ) -> None:
        self._settings = settings
        self._snapshots = snapshots

    def execute(self) -> InitialUiPreferences:
        with self._snapshots.snapshot():
            theme, context_visible, _ = _validated_preferences(self._settings)
        return InitialUiPreferences(theme, context_visible)


class InspectManualSettingsService:
    """Project validated preferences and the immutable safe configuration view."""

    def __init__(
        self,
        *,
        settings: SettingsRepository,
        snapshots: ReadOnlySnapshotBoundary,
        configuration: ConfigurationSnapshot,
    ) -> None:
        self._settings = settings
        self._snapshots = snapshots
        self._configuration = configuration

    def execute(
        self,
        request: InspectManualSettingsRequest,
    ) -> InspectManualSettingsResult:
        if not isinstance(request, InspectManualSettingsRequest):
            raise TypeError(
                "InspectManualSettingsService requires its empty request type."
            )
        try:
            with self._snapshots.snapshot():
                theme, context_visible, _ = _validated_preferences(self._settings)
                configuration = _configuration_view(self._configuration)
            return ManualSettingsReadyResult(
                ManualSettingsView(theme, context_visible, configuration)
            )
        except (DomainError, PersistenceError, TypeError, ValueError):
            return ManualSettingsLoadFailureResult()


def _validation_failure(
    updates: tuple[SettingUpdate, ...],
) -> ManualSettingsValidationFailureResult | None:
    by_key: dict[str, SettingUpdate] = {}
    for update in updates:
        if not isinstance(update, SettingUpdate):
            return ManualSettingsValidationFailureResult(
                code="SETTING_KEY_UNKNOWN",
                errors=(
                    SettingsFieldError(
                        SettingsField.UNKNOWN,
                        "Only permitted presentation settings can be changed.",
                    ),
                ),
            )
        by_key.setdefault(update.key, update)

    errors: list[SettingsFieldError] = []
    invalid_value = False
    not_editable = False
    unknown = False
    theme_update = by_key.get(_THEME_KEY)
    if theme_update is not None and not isinstance(theme_update.value, UiTheme):
        invalid_value = True
        errors.append(
            SettingsFieldError(
                SettingsField.THEME,
                "Theme must be System, Light, or Dark.",
            )
        )
    context_update = by_key.get(_CONTEXT_VISIBLE_KEY)
    if context_update is not None and not isinstance(context_update.value, bool):
        invalid_value = True
        errors.append(
            SettingsFieldError(
                SettingsField.CONTEXT_PANEL_VISIBLE,
                "Show context inspection must be true or false.",
            )
        )
    if _LAST_CONVERSATION_KEY in by_key:
        not_editable = True
        errors.append(
            SettingsFieldError(
                SettingsField.LAST_SELECTED_CONVERSATION,
                "This setting is not editable here.",
            )
        )
    for key in sorted(by_key):
        if key not in _PERMITTED_KEYS:
            unknown = True
            errors.append(
                SettingsFieldError(
                    SettingsField.UNKNOWN,
                    "Only permitted presentation settings can be changed.",
                )
            )
    if not updates:
        unknown = True
        errors.append(
            SettingsFieldError(
                SettingsField.UNKNOWN,
                "Only permitted presentation settings can be changed.",
            )
        )
    if not errors:
        return None
    code = (
        "SETTING_KEY_UNKNOWN"
        if unknown
        else "SETTING_KEY_NOT_EDITABLE"
        if not_editable
        else "SETTING_VALUE_INVALID"
    )
    return ManualSettingsValidationFailureResult(
        code=code,
        errors=tuple(errors),
    )


class UpdateManualSettingsService:
    """Atomically upsert only changed editable preferences with one timestamp."""

    def __init__(
        self,
        *,
        settings: SettingsRepository,
        transactions: TransactionBoundary,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._transactions = transactions
        self._clock = clock

    def execute(
        self,
        request: UpdateManualSettingsRequest,
    ) -> UpdateManualSettingsResult:
        if not isinstance(request, UpdateManualSettingsRequest):
            raise TypeError(
                "UpdateManualSettingsService requires its request type."
            )
        validation = _validation_failure(request.values)
        if validation is not None:
            return validation

        updates = {update.key: update for update in request.values}
        try:
            with self._transactions.transaction():
                current_theme, current_visible, _ = _validated_preferences(
                    self._settings
                )
                effective_theme = (
                    updates[_THEME_KEY].value
                    if _THEME_KEY in updates
                    else current_theme
                )
                effective_visible = (
                    updates[_CONTEXT_VISIBLE_KEY].value
                    if _CONTEXT_VISIBLE_KEY in updates
                    else current_visible
                )
                if not isinstance(effective_theme, UiTheme) or not isinstance(
                    effective_visible, bool
                ):
                    raise LifecycleInvariantError(
                        "Validated settings update lost its closed value type."
                    )
                changed_keys = tuple(
                    key
                    for key, changed in (
                        (
                            ManualSettingKey.UI_THEME,
                            effective_theme is not current_theme,
                        ),
                        (
                            ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE,
                            effective_visible != current_visible,
                        ),
                    )
                    if changed
                )
                if not changed_keys:
                    raise LifecycleInvariantError(
                        "Settings application request must contain a changed value."
                    )
                updated_at = self._clock.now()
                for key in changed_keys:
                    value = (
                        effective_theme.value
                        if key is ManualSettingKey.UI_THEME
                        else effective_visible
                    )
                    self._settings.set(
                        key=key.value,
                        value=value,
                        updated_at=updated_at,
                    )
            return ManualSettingsUpdateSucceededResult(
                effective_theme=effective_theme,
                effective_context_panel_visible=effective_visible,
                changed_keys=changed_keys,
            )
        except (DomainError, PersistenceError, TypeError, ValueError):
            return ManualSettingsMutationFailureResult()


__all__ = [
    "InspectManualSettingsService",
    "LoadInitialUiPreferencesService",
    "ReadOnlySnapshotBoundary",
    "UpdateManualSettingsService",
]
