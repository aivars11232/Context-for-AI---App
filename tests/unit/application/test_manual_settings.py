"""Deterministic TASK-0017 manual-settings application tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from context_for_ai.application.contracts import (
    InspectManualSettingsRequest,
    ManualSettingsLoadFailureResult,
    ManualSettingsReadyResult,
    ManualSettingsUpdateSucceededResult,
    ManualSettingsValidationFailureResult,
    SettingUpdate,
    UiTheme,
    UpdateManualSettingsRequest,
)
from context_for_ai.application.manual_settings import (
    InspectManualSettingsService,
    LoadInitialUiPreferencesService,
    UpdateManualSettingsService,
)
from context_for_ai.bootstrap.shell_composition import configuration_snapshot_from
from context_for_ai.domain.ports.records import Setting
from context_for_ai.infrastructure.configuration import load_configuration


class _Settings:
    def __init__(self, rows: tuple[Setting, ...] = ()) -> None:
        self.rows = {row.key: row for row in rows}
        self.writes: list[tuple[str, object, datetime]] = []

    def get(self, key: str) -> Setting | None:
        return self.rows.get(key)

    def list_all(self) -> tuple[Setting, ...]:
        return tuple(self.rows[key] for key in sorted(self.rows))

    def set(self, *, key: str, value: object, updated_at: datetime) -> Setting:
        row = Setting(key, value, updated_at)  # type: ignore[arg-type]
        self.rows[key] = row
        self.writes.append((key, value, updated_at))
        return row


class _Boundary:
    def __init__(self) -> None:
        self.entries = 0

    @contextmanager
    def snapshot(self):  # type: ignore[no-untyped-def]
        self.entries += 1
        yield

    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        self.entries += 1
        yield


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


def _stamp() -> datetime:
    return datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_initial_preferences_use_defaults_without_writes() -> None:
    settings = _Settings()
    snapshots = _Boundary()

    result = LoadInitialUiPreferencesService(
        settings=settings,
        snapshots=snapshots,
    ).execute()

    assert result.theme is UiTheme.SYSTEM
    assert result.context_panel_visible is True
    assert snapshots.entries == 1
    assert settings.writes == []


def test_manual_settings_projects_only_exact_safe_configuration(
    fixture_application_root: Path,
) -> None:
    loaded = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    result = InspectManualSettingsService(
        settings=_Settings(),
        snapshots=_Boundary(),
        configuration=configuration_snapshot_from(loaded),
    ).execute(InspectManualSettingsRequest())

    assert isinstance(result, ManualSettingsReadyResult)
    view = result.view.configuration
    assert tuple(category.name.value for category in view.categories) == (
        "Application",
        "Model",
        "Storage",
        "Memory",
        "Validation",
        "Logging",
        "Security",
    )
    visible = tuple(
        (field.label, field.value_text, field.origin.display_label)
        for category in view.categories
        for field in category.fields
    )
    assert ("Data location", "Local path (value hidden)", "Local YAML") in visible
    assert ("Maximum automatic revisions", "2", "Local YAML") in visible
    assert ("Retention", "30 days", "Local YAML") in visible
    rendered = repr(result)
    assert loaded.model.name not in rendered
    assert loaded.model.base_url not in rendered
    assert str(loaded.app.data_directory) not in rendered
    assert len(view.fingerprint) == 64


def test_missing_configuration_origin_fails_complete_settings_query(
    fixture_application_root: Path,
) -> None:
    snapshot = configuration_snapshot_from(
        load_configuration(
            application_root=fixture_application_root,
            environ={},
        )
    )
    object.__setattr__(snapshot, "scalar_origins", ())

    result = InspectManualSettingsService(
        settings=_Settings(),
        snapshots=_Boundary(),
        configuration=snapshot,
    ).execute(InspectManualSettingsRequest())

    assert isinstance(result, ManualSettingsLoadFailureResult)
    assert result.safe_message == "Settings could not be loaded safely."


def test_settings_update_writes_changed_keys_atomically_with_one_clock() -> None:
    settings = _Settings()
    transactions = _Boundary()
    clock = _Clock(_stamp())
    service = UpdateManualSettingsService(
        settings=settings,
        transactions=transactions,
        clock=clock,
    )

    result = service.execute(
        UpdateManualSettingsRequest(
            (
                SettingUpdate("ui.theme", UiTheme.DARK),
                SettingUpdate("ui.context_panel_visible", False),
            )
        )
    )

    assert isinstance(result, ManualSettingsUpdateSucceededResult)
    assert tuple(key.value for key in result.changed_keys) == (
        "ui.theme",
        "ui.context_panel_visible",
    )
    assert clock.calls == 1
    assert transactions.entries == 1
    assert settings.writes == [
        ("ui.theme", "DARK", _stamp()),
        ("ui.context_panel_visible", False, _stamp()),
    ]


def test_invalid_and_forbidden_settings_reject_before_clock_or_write() -> None:
    settings = _Settings()
    transactions = _Boundary()
    clock = _Clock(_stamp())
    service = UpdateManualSettingsService(
        settings=settings,
        transactions=transactions,
        clock=clock,
    )

    result = service.execute(
        UpdateManualSettingsRequest(
            (
                SettingUpdate("ui.theme", "DARK"),
                SettingUpdate("ui.last_selected_conversation_id", None),
                SettingUpdate("secret.key", "sentinel"),
            )
        )
    )

    assert isinstance(result, ManualSettingsValidationFailureResult)
    assert result.code == "SETTING_KEY_UNKNOWN"
    assert tuple(error.field.value for error in result.errors) == (
        "THEME",
        "LAST_SELECTED_CONVERSATION",
        "UNKNOWN",
    )
    assert clock.calls == 0
    assert transactions.entries == 0
    assert settings.writes == []
