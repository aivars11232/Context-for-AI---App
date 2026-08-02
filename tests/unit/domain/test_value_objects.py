"""Tests for UUID, score, UTC, and immutable JSON value objects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from context_for_ai.domain.errors import (
    DomainValidationError,
    InvalidDomainIdError,
    InvalidTimestampError,
    ScoreOutOfRangeError,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
    format_utc_timestamp,
    freeze_json,
    parse_utc_timestamp,
    utc_now,
)


def test_domain_id_normalizes_text_and_has_value_equality() -> None:
    lower = DomainId("12345678-1234-5678-9234-567812345678")
    upper = DomainId("12345678-1234-5678-9234-567812345678".upper())

    assert lower == upper
    assert str(lower) == "12345678-1234-5678-9234-567812345678"
    with pytest.raises(FrozenInstanceError):
        lower.value = upper.value  # type: ignore[misc]


@pytest.mark.parametrize("value", ["not-a-uuid", "", 12, None])
def test_domain_id_rejects_invalid_values(value: object) -> None:
    with pytest.raises(InvalidDomainIdError):
        DomainId(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("0"), "0.50", 1, 0.123456])
def test_unit_score_preserves_valid_unrounded_values(value: Decimal | str | int | float) -> None:
    score = UnitScore(value)

    assert Decimal(0) <= score.value <= Decimal(1)
    assert UnitScore(score.value) == score


@pytest.mark.parametrize(
    "value",
    [Decimal("-0.01"), "1.01", float("nan"), float("inf"), True, "invalid"],
)
def test_unit_score_rejects_non_finite_and_out_of_range_values(value: object) -> None:
    with pytest.raises(ScoreOutOfRangeError):
        UnitScore(value)  # type: ignore[arg-type]


def test_utc_helpers_normalize_offsets_and_emit_z_suffix() -> None:
    parsed = parse_utc_timestamp("2026-08-02T12:30:00+02:00")

    assert parsed == datetime(2026, 8, 2, 10, 30, tzinfo=timezone.utc)
    assert format_utc_timestamp(parsed) == "2026-08-02T10:30:00Z"


def test_utc_helpers_reject_naive_time_and_use_injected_clock_once() -> None:
    calls = 0
    local_time = datetime(
        2026,
        8,
        2,
        12,
        30,
        tzinfo=timezone(timedelta(hours=2)),
    )

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return local_time

    assert utc_now(clock) == datetime(2026, 8, 2, 10, 30, tzinfo=timezone.utc)
    assert calls == 1
    with pytest.raises(InvalidTimestampError):
        ensure_utc(datetime(2026, 8, 2, 10, 30))


def test_frozen_json_is_recursive_order_independent_and_detached_from_input() -> None:
    source = {"nested": {"items": [1, "two"]}, "flag": True}
    first = FrozenJsonObject(source)
    second = FrozenJsonObject({"flag": True, "nested": {"items": [1, "two"]}})

    nested = source["nested"]
    assert isinstance(nested, dict)
    items = nested["items"]
    assert isinstance(items, list)
    items.append(3)

    assert first == second
    assert first["nested"] == FrozenJsonObject({"items": [1, "two"]})
    assert hash(first) == hash(second)
    with pytest.raises(TypeError):
        first["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize("value", [{1: "bad-key"}, float("nan"), Decimal("0.5")])
def test_frozen_json_rejects_values_that_are_not_valid_json(value: object) -> None:
    with pytest.raises(DomainValidationError):
        freeze_json(value)
