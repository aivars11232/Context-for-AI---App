"""Dependency-free value objects shared by canonical domain representations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math
from typing import Callable
from uuid import UUID, uuid4

from context_for_ai.domain.errors import (
    DomainValidationError,
    InvalidDomainIdError,
    InvalidTimestampError,
    ScoreOutOfRangeError,
)


UTC = timezone.utc


@dataclass(frozen=True, slots=True, order=True)
class DomainId:
    """A validated UUID identifier with canonical text serialization."""

    value: UUID

    def __init__(self, value: UUID | str) -> None:
        try:
            parsed = value if isinstance(value, UUID) else UUID(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise InvalidDomainIdError(f"Invalid UUID domain identifier: {value!r}.") from error
        object.__setattr__(self, "value", parsed)

    @classmethod
    def new(cls) -> DomainId:
        """Create a new random UUID identifier at an explicit domain boundary."""

        return cls(uuid4())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True, order=True)
class UnitScore:
    """An exact finite decimal score in the inclusive interval ``[0, 1]``."""

    value: Decimal

    def __init__(self, value: Decimal | int | float | str) -> None:
        if isinstance(value, bool):
            raise ScoreOutOfRangeError("A boolean is not a canonical unit score.")
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ScoreOutOfRangeError(f"Invalid unit score: {value!r}.") from error
        if not parsed.is_finite() or not Decimal(0) <= parsed <= Decimal(1):
            raise ScoreOutOfRangeError(
                f"Unit score must be finite and between 0 and 1: {value!r}."
            )
        object.__setattr__(self, "value", parsed)

    def __float__(self) -> float:
        return float(self.value)

    def __str__(self) -> str:
        return str(self.value)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` normalized to UTC, rejecting naive timestamps."""

    if not isinstance(value, datetime):
        raise InvalidTimestampError(f"Expected a datetime, received {type(value).__name__}.")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as error:
        raise InvalidTimestampError(f"Invalid timezone-aware timestamp: {value!r}.") from error
    if value.tzinfo is None or offset is None:
        raise InvalidTimestampError("Domain timestamps must be timezone-aware.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise InvalidTimestampError(f"Timestamp cannot be normalized to UTC: {value!r}.") from error


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value:
        raise InvalidTimestampError("UTC timestamp text must be non-empty.")
    normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise InvalidTimestampError(f"Invalid ISO-8601 timestamp: {value!r}.") from error
    return ensure_utc(parsed)


def format_utc_timestamp(value: datetime) -> str:
    """Serialize a timezone-aware timestamp as canonical UTC ISO-8601 text."""

    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def utc_now(clock: Callable[[], datetime] | None = None) -> datetime:
    """Read a clock once and return a validated UTC-aware timestamp."""

    current = clock() if clock is not None else datetime.now(UTC)
    return ensure_utc(current)


@dataclass(frozen=True, slots=True)
class FrozenJsonObject(Mapping[str, object]):
    """An immutable JSON object whose nested arrays and objects are frozen."""

    _items: tuple[tuple[str, FrozenJsonValue], ...]

    def __init__(self, value: Mapping[str, object]) -> None:
        if any(not isinstance(key, str) for key in value):
            raise DomainValidationError("JSON object keys must be strings.")
        items = [(key, freeze_json(value[key])) for key in sorted(value)]
        object.__setattr__(self, "_items", tuple(items))

    def __getitem__(self, key: str) -> FrozenJsonValue:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)


type JsonScalar = None | bool | int | float | str
type FrozenJsonValue = JsonScalar | FrozenJsonObject | tuple[FrozenJsonValue, ...]


def freeze_json(value: object) -> FrozenJsonValue:
    """Convert a valid JSON-like value to an immutable recursive value."""

    if isinstance(value, FrozenJsonObject):
        return value
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainValidationError("JSON numbers must be finite.")
        return value
    if isinstance(value, Mapping):
        return FrozenJsonObject(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise DomainValidationError(
        f"Unsupported JSON value type: {type(value).__name__}."
    )
