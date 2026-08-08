"""Dependency-free value objects shared by canonical domain representations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
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


def canonical_decimal_string(value: Decimal) -> str:
    """Serialize one finite decimal in canonical fixed-point notation."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError("Canonical decimal serialization requires a finite Decimal.")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


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


type JsonScalar = None | bool | int | float | Decimal | str
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
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DomainValidationError("JSON decimal numbers must be finite.")
        return value
    if isinstance(value, Mapping):
        return FrozenJsonObject(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise DomainValidationError(
        f"Unsupported JSON value type: {type(value).__name__}."
    )


def _canonical_json_string(value: str) -> str:
    rendered: list[str] = ['"']
    short_escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    for character in value:
        escaped = short_escapes.get(character)
        if escaped is not None:
            rendered.append(escaped)
            continue
        code_point = ord(character)
        if 0xD800 <= code_point <= 0xDFFF:
            raise DomainValidationError(
                "Canonical JSON strings cannot contain lone UTF-16 surrogates."
            )
        if (
            code_point <= 0x001F
            or 0x007F <= code_point <= 0x009F
            or code_point in (0x2028, 0x2029)
        ):
            rendered.append(f"\\u{code_point:04x}")
        else:
            rendered.append(character)
    rendered.append('"')
    return "".join(rendered)


def canonical_json(value: object) -> str:
    """Return strict one-line canonical JSON for packet and prompt values.

    Generic durable JSON may continue to contain finite binary floats. The
    packet codec is deliberately stricter and rejects them recursively.
    """

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return canonical_decimal_string(value)
    if isinstance(value, float):
        raise DomainValidationError(
            "Canonical packet JSON rejects binary floating-point values."
        )
    if isinstance(value, str):
        return _canonical_json_string(value)
    if isinstance(value, FrozenJsonObject):
        items = value._items
        return "{" + ",".join(
            f"{_canonical_json_string(key)}:{canonical_json(item)}"
            for key, item in items
        ) + "}"
    if isinstance(value, Mapping):
        return canonical_json(FrozenJsonObject(value))
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise DomainValidationError(
        f"Unsupported canonical JSON value type: {type(value).__name__}."
    )


def parse_canonical_json_object(value: str) -> FrozenJsonObject:
    """Parse one strict canonical JSON object and reject alternate encodings."""

    if not isinstance(value, str) or not value:
        raise DomainValidationError("Canonical JSON text must be non-empty.")

    def reject_constant(raw: str) -> object:
        raise DomainValidationError(f"Canonical JSON rejects {raw}.")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise DomainValidationError(
                    f"Canonical JSON contains duplicate key {key!r}."
                )
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except DomainValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise DomainValidationError("Invalid canonical JSON object.") from error
    if not isinstance(parsed, Mapping):
        raise DomainValidationError("Canonical packet JSON must be an object.")
    frozen = FrozenJsonObject(parsed)
    if canonical_json(frozen) != value:
        raise DomainValidationError("Packet JSON is not in canonical form.")
    return frozen
