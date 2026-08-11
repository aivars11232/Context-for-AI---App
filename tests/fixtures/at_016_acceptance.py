"""Closed test-layer gate and evidence support for AT-016."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime
import errno
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from types import MappingProxyType

from context_for_ai.domain.ports.model_gateway import (
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.infrastructure.configuration.ollama_model import (
    InvalidOllamaModelIdentity,
    normalize_ollama_model_identity,
)
from tests.fixtures.ollama_live import (
    OllamaLiveOptIn,
    classify_ollama_live_opt_in,
)


ACCEPTANCE_ID = "AT-016"
EVIDENCE_SCHEMA_VERSION = "at-016-evidence-v1"
FIXTURE_VERSION = "at-016-local-ollama-smoke-v1"
MODEL_NAME_VARIABLE = "CONTEXT_FOR_AI__MODEL__NAME"
MODEL_BASE_URL_VARIABLE = "CONTEXT_FOR_AI__MODEL__BASE_URL"
SMOKE_SENTINEL = "CONTEXT_FOR_AI_SMOKE_OK"
LIMITATIONS = (
    "MODEL_SPECIFIC_LIVE_ACCEPTANCE",
    "NON_CRYPTOGRAPHIC_LOCALITY_ATTESTATION",
    "STRUCTURAL_SMOKE_ORACLE_ONLY",
)
EVIDENCE_TOP_LEVEL_KEYS = frozenset(
    {
        "acceptance_id",
        "configuration_fingerprint",
        "failure",
        "fixture_version",
        "gateway_elapsed_microseconds",
        "limitations",
        "model",
        "os",
        "prerequisites",
        "provider",
        "recorded_at_utc",
        "result",
        "schema_version",
    }
)

_SAFE_FAILURES = MappingProxyType(
    {
        "CONFIGURATION": frozenset(
            {"MODEL_NAME_REQUIRED", "CONFIGURATION_INVALID"}
        ),
        "STARTUP": frozenset({"STARTUP_FAILED"}),
        "TRANSPORT": frozenset(
            {
                "PROVIDER_UNAVAILABLE",
                "MODEL_NOT_FOUND",
                "MODEL_TIMEOUT",
                "MODEL_CANCELLED",
                "INVALID_PROVIDER_RESPONSE",
            }
        ),
        "VALIDATION": frozenset({"VALIDATION_EXHAUSTED"}),
        "PERSISTENCE": frozenset({"PERSISTENCE_ERROR"}),
        "LINEAGE": frozenset({"LINEAGE_MISMATCH"}),
        "TRACE": frozenset({"TRACE_ASSERTION_FAILED"}),
        "REDACTION": frozenset({"REDACTION_ASSERTION_FAILED"}),
        "UI": frozenset({"UI_ASSERTION_FAILED"}),
        "EVIDENCE": frozenset({"OS_METADATA_UNAVAILABLE"}),
        "ACCEPTANCE": frozenset({"UNEXPECTED_RESULT"}),
    }
)
_TIMESTAMP_PATTERN = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z"
)
_FINGERPRINT_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"\A[A-Za-z]:[\\/]")
_STATIC_PROHIBITED_FRAGMENTS = (
    ".env",
    "http://",
    "https://",
    "authorization:",
    "proxy-authorization:",
    "cookie:",
    "bearer ",
    "begin private key",
)
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class At016EvidenceValidationError(ValueError):
    """Report a closed evidence-schema or redaction violation."""


class At016EvidenceLifecycleError(RuntimeError):
    """Prevent evidence work before exact opt-in starts its lifecycle."""


class At016EvidenceWriteError(RuntimeError):
    """Report only the safe completion-report writer code."""

    code = "EVIDENCE_WRITE_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class At016EvidenceCollisionError(At016EvidenceWriteError):
    """Report a no-overwrite final-name collision without exposing a path."""


@dataclass(frozen=True, slots=True)
class At016Failure:
    """One safe closed AT-016 failure pair."""

    stage: str
    code: str

    def __post_init__(self) -> None:
        if self.stage not in _SAFE_FAILURES or self.code not in _SAFE_FAILURES[
            self.stage
        ]:
            raise At016EvidenceValidationError(
                "AT-016 failure pair is outside the closed vocabulary."
            )

    def to_document(self) -> dict[str, str]:
        return {"code": self.code, "stage": self.stage}


@dataclass(frozen=True, slots=True)
class At016Gate:
    """One side-effect-free opt-in and loader handoff decision."""

    opt_in: OllamaLiveOptIn
    artifact_lifecycle_started: bool
    loader_environment: Mapping[str, str]
    failure: At016Failure | None = None

    def __post_init__(self) -> None:
        loader_environment = dict(self.loader_environment)
        if set(loader_environment) - {
            MODEL_NAME_VARIABLE,
            MODEL_BASE_URL_VARIABLE,
        }:
            raise ValueError("AT-016 loader environment contains an unknown key.")
        if self.artifact_lifecycle_started != (
            self.opt_in is OllamaLiveOptIn.ENABLED
        ):
            raise ValueError("AT-016 artifact lifecycle disagrees with opt-in.")
        if self.failure is not None and not self.artifact_lifecycle_started:
            raise ValueError("AT-016 pre-lifecycle gate cannot own an artifact failure.")
        object.__setattr__(
            self,
            "loader_environment",
            MappingProxyType(loader_environment),
        )


@dataclass(frozen=True, slots=True)
class At016Prerequisites:
    """The only statuses admitted to an AT-016 evidence artifact."""

    default_non_live_suite: str
    at_001_through_at_015: str

    def __post_init__(self) -> None:
        if (
            self.default_non_live_suite != "PASSED"
            or self.at_001_through_at_015 != "PASSED"
        ):
            raise At016EvidenceValidationError(
                "AT-016 prerequisites must both be PASSED."
            )

    def to_document(self) -> dict[str, str]:
        return {
            "at_001_through_at_015": self.at_001_through_at_015,
            "default_non_live_suite": self.default_non_live_suite,
        }


@dataclass(frozen=True, slots=True)
class At016ModelEvidence:
    identity: str
    tag: str

    def to_document(self) -> dict[str, str]:
        return {"identity": self.identity, "tag": self.tag}


@dataclass(frozen=True, slots=True)
class At016ProviderEvidence:
    cloud_disable_source: str
    version: str
    name: str = "ollama"

    def to_document(self) -> dict[str, str]:
        return {
            "cloud_disable_source": self.cloud_disable_source,
            "name": self.name,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class At016OsEvidence:
    machine: str
    release: str
    system: str

    def to_document(self) -> dict[str, str]:
        return {
            "machine": self.machine,
            "release": self.release,
            "system": self.system,
        }


@dataclass(frozen=True, slots=True)
class At016Evidence:
    """One closed standalone AT-016 evidence value."""

    configuration_fingerprint: str | None
    failure: At016Failure | None
    gateway_elapsed_microseconds: int | None
    model: At016ModelEvidence | None
    os: At016OsEvidence | None
    prerequisites: At016Prerequisites
    provider: At016ProviderEvidence | None
    recorded_at_utc: str

    @property
    def result(self) -> str:
        return "PASSED" if self.failure is None else "FAILED"

    def to_document(self) -> dict[str, object]:
        return {
            "acceptance_id": ACCEPTANCE_ID,
            "configuration_fingerprint": self.configuration_fingerprint,
            "failure": None if self.failure is None else self.failure.to_document(),
            "fixture_version": FIXTURE_VERSION,
            "gateway_elapsed_microseconds": self.gateway_elapsed_microseconds,
            "limitations": list(LIMITATIONS),
            "model": None if self.model is None else self.model.to_document(),
            "os": None if self.os is None else self.os.to_document(),
            "prerequisites": self.prerequisites.to_document(),
            "provider": (
                None if self.provider is None else self.provider.to_document()
            ),
            "recorded_at_utc": self.recorded_at_utc,
            "result": self.result,
            "schema_version": EVIDENCE_SCHEMA_VERSION,
        }


def evaluate_at_016_gate(environ: Mapping[str, str]) -> At016Gate:
    """Classify opt-in before any configuration, provider, or artifact work."""

    opt_in = classify_ollama_live_opt_in(environ)
    if opt_in is OllamaLiveOptIn.ABSENT:
        return At016Gate(opt_in, False, {})
    if opt_in is OllamaLiveOptIn.INVALID:
        return At016Gate(opt_in, False, {})

    loader_environment = {
        key: environ[key]
        for key in (MODEL_NAME_VARIABLE, MODEL_BASE_URL_VARIABLE)
        if key in environ
    }
    model_name = loader_environment.get(MODEL_NAME_VARIABLE)
    failure = (
        At016Failure("CONFIGURATION", "MODEL_NAME_REQUIRED")
        if model_name is None or model_name == ""
        else None
    )
    return At016Gate(opt_in, True, loader_environment, failure)


def validated_prerequisites(
    *,
    default_non_live_suite: str,
    at_001_through_at_015: str,
) -> At016Prerequisites:
    """Validate the two prerequisite statuses admitted by the artifact."""

    return At016Prerequisites(
        default_non_live_suite,
        at_001_through_at_015,
    )


def retain_first_failure(
    existing: At016Failure | None,
    later: At016Failure,
) -> At016Failure:
    """Retain the first safely classifiable failure."""

    return later if existing is None else existing


def project_transport_failure(outcome: object) -> At016Failure:
    """Project one current gateway failure to the closed evidence vocabulary."""

    projections = (
        (ModelCancelledFailure, "MODEL_CANCELLED"),
        (ModelTimeoutFailure, "MODEL_TIMEOUT"),
        (ModelNotFoundFailure, "MODEL_NOT_FOUND"),
        (InvalidProviderResponseFailure, "INVALID_PROVIDER_RESPONSE"),
        (ProviderUnavailableFailure, "PROVIDER_UNAVAILABLE"),
    )
    for failure_type, code in projections:
        if isinstance(outcome, failure_type):
            return At016Failure("TRANSPORT", code)
    raise At016EvidenceValidationError(
        "Gateway outcome has no AT-016 transport projection."
    )


def model_evidence(identity: str) -> At016ModelEvidence:
    """Return the normalized identity and explicit or inserted tag."""

    try:
        normalized = normalize_ollama_model_identity(identity)
    except InvalidOllamaModelIdentity as error:
        raise At016EvidenceValidationError(
            "AT-016 model evidence is invalid."
        ) from error
    return At016ModelEvidence(normalized.value, normalized.tag)


def provider_evidence(metadata: Mapping[str, object]) -> At016ProviderEvidence:
    """Project only allowlisted fields from durable completed-generation metadata."""

    provider = metadata.get("provider")
    version = metadata.get("provider_version")
    source = metadata.get("cloud_disable_source")
    if (
        provider != "ollama"
        or not isinstance(version, str)
        or not version.strip()
        or source not in {"env", "config", "both"}
    ):
        raise At016EvidenceValidationError(
            "Durable provider metadata cannot form AT-016 evidence."
        )
    return At016ProviderEvidence(str(source), version)


def format_recorded_at(value: datetime) -> str:
    """Render one aware timestamp at exact UTC microsecond precision."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise At016EvidenceValidationError(
            "AT-016 recorded time must be timezone-aware."
        )
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def collect_os_evidence() -> At016OsEvidence | None:
    """Collect only the three AT-016-authorized standard-library OS values."""

    try:
        system = platform.system().strip()
        release = platform.release().strip()
        machine = platform.machine().strip()
    except Exception:
        return None
    if not system or not release or not machine:
        return None
    return At016OsEvidence(machine=machine, release=release, system=system)


def finalize_evidence(
    *,
    recorded_at: datetime,
    prerequisites: At016Prerequisites,
    configuration_fingerprint: str | None = None,
    failure: At016Failure | None = None,
    gateway_elapsed_microseconds: int | None = None,
    model: At016ModelEvidence | None = None,
    provider: At016ProviderEvidence | None = None,
) -> At016Evidence:
    """Finalize OS evidence without replacing an earlier safe failure."""

    os_evidence = collect_os_evidence()
    if os_evidence is None:
        failure = retain_first_failure(
            failure,
            At016Failure("EVIDENCE", "OS_METADATA_UNAVAILABLE"),
        )
    return At016Evidence(
        configuration_fingerprint=configuration_fingerprint,
        failure=failure,
        gateway_elapsed_microseconds=gateway_elapsed_microseconds,
        model=model,
        os=os_evidence,
        prerequisites=prerequisites,
        provider=provider,
        recorded_at_utc=format_recorded_at(recorded_at),
    )


def _exact_keys(
    value: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise At016EvidenceValidationError(
            f"AT-016 {label} must contain exactly its closed keys."
        )
    return value


def _required_text(value: object, label: str, *, stripped: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise At016EvidenceValidationError(
            f"AT-016 {label} must be non-empty text."
        )
    if stripped and value != value.strip():
        raise At016EvidenceValidationError(
            f"AT-016 {label} must already be stripped."
        )
    return value


def _validate_timestamp(value: object) -> str:
    timestamp = _required_text(value, "recorded_at_utc")
    if _TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
        raise At016EvidenceValidationError(
            "AT-016 recorded_at_utc has an invalid shape."
        )
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as error:
        raise At016EvidenceValidationError(
            "AT-016 recorded_at_utc is not a valid timestamp."
        ) from error
    return timestamp


def _document_strings(value: object) -> tuple[str, ...]:
    strings: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                strings.append(str(key))
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(strings)


def validate_prohibited_content(
    document: Mapping[str, object],
    *,
    prohibited_values: Iterable[str] = (),
) -> None:
    """Reject content outside the artifact's safe allowlist without echoing it."""

    values = _document_strings(document)
    private = tuple(
        value for value in prohibited_values if isinstance(value, str) and value
    )
    for value in values:
        folded = value.casefold()
        if (
            value.startswith("/")
            or _WINDOWS_ABSOLUTE_PATTERN.match(value) is not None
            or any(fragment in folded for fragment in _STATIC_PROHIBITED_FRAGMENTS)
            or any(secret in value for secret in private)
        ):
            raise At016EvidenceValidationError(
                "AT-016 evidence contains prohibited content."
            )


def validate_evidence_document(
    document: Mapping[str, object],
    *,
    prohibited_values: Iterable[str] = (),
) -> None:
    """Validate the complete closed AT-016 document and cross-field rules."""

    value = _exact_keys(document, EVIDENCE_TOP_LEVEL_KEYS, "evidence document")
    if value["acceptance_id"] != ACCEPTANCE_ID:
        raise At016EvidenceValidationError("AT-016 acceptance_id is invalid.")
    if value["fixture_version"] != FIXTURE_VERSION:
        raise At016EvidenceValidationError("AT-016 fixture_version is invalid.")
    if value["schema_version"] != EVIDENCE_SCHEMA_VERSION:
        raise At016EvidenceValidationError("AT-016 schema_version is invalid.")

    fingerprint = value["configuration_fingerprint"]
    if fingerprint is not None and (
        not isinstance(fingerprint, str)
        or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
    ):
        raise At016EvidenceValidationError(
            "AT-016 configuration fingerprint is invalid."
        )

    failure_value = value["failure"]
    failure: At016Failure | None
    if failure_value is None:
        failure = None
    else:
        failure_object = _exact_keys(
            failure_value,
            frozenset({"code", "stage"}),
            "failure",
        )
        failure = At016Failure(
            _required_text(failure_object["stage"], "failure.stage"),
            _required_text(failure_object["code"], "failure.code"),
        )

    elapsed = value["gateway_elapsed_microseconds"]
    if elapsed is not None and (
        not isinstance(elapsed, int) or isinstance(elapsed, bool) or elapsed < 0
    ):
        raise At016EvidenceValidationError(
            "AT-016 gateway elapsed value is invalid."
        )
    if value["limitations"] != list(LIMITATIONS):
        raise At016EvidenceValidationError("AT-016 limitations are invalid.")

    model_value = value["model"]
    if model_value is not None:
        model_object = _exact_keys(
            model_value,
            frozenset({"identity", "tag"}),
            "model",
        )
        identity = _required_text(model_object["identity"], "model.identity")
        tag = _required_text(model_object["tag"], "model.tag")
        try:
            normalized = normalize_ollama_model_identity(identity)
        except InvalidOllamaModelIdentity as error:
            raise At016EvidenceValidationError(
                "AT-016 model identity is invalid."
            ) from error
        if normalized.value != identity or normalized.tag != tag:
            raise At016EvidenceValidationError(
                "AT-016 model evidence is not normalized."
            )

    os_value = value["os"]
    if os_value is not None:
        os_object = _exact_keys(
            os_value,
            frozenset({"machine", "release", "system"}),
            "os",
        )
        for key in ("machine", "release", "system"):
            _required_text(os_object[key], f"os.{key}", stripped=True)

    prerequisites = _exact_keys(
        value["prerequisites"],
        frozenset({"at_001_through_at_015", "default_non_live_suite"}),
        "prerequisites",
    )
    At016Prerequisites(
        _required_text(
            prerequisites["default_non_live_suite"],
            "prerequisites.default_non_live_suite",
        ),
        _required_text(
            prerequisites["at_001_through_at_015"],
            "prerequisites.at_001_through_at_015",
        ),
    )

    provider_value = value["provider"]
    if provider_value is not None:
        provider_object = _exact_keys(
            provider_value,
            frozenset({"cloud_disable_source", "name", "version"}),
            "provider",
        )
        if provider_object["name"] != "ollama" or provider_object[
            "cloud_disable_source"
        ] not in {"env", "config", "both"}:
            raise At016EvidenceValidationError(
                "AT-016 provider evidence is invalid."
            )
        _required_text(provider_object["version"], "provider.version")

    _validate_timestamp(value["recorded_at_utc"])
    result = value["result"]
    if result not in {"PASSED", "FAILED"}:
        raise At016EvidenceValidationError("AT-016 result is invalid.")
    if result == "PASSED":
        if (
            failure is not None
            or fingerprint is None
            or model_value is None
            or provider_value is None
            or os_value is None
            or elapsed is None
        ):
            raise At016EvidenceValidationError(
                "AT-016 passed evidence lacks required completed fields."
            )
    elif failure is None:
        raise At016EvidenceValidationError(
            "AT-016 failed evidence requires one safe failure."
        )
    if (fingerprint is None) != (model_value is None):
        raise At016EvidenceValidationError(
            "AT-016 configuration and model evidence must appear together."
        )
    if (provider_value is None) != (elapsed is None):
        raise At016EvidenceValidationError(
            "AT-016 provider and elapsed evidence must appear together."
        )
    if (
        failure == At016Failure("EVIDENCE", "OS_METADATA_UNAVAILABLE")
        and os_value is not None
    ):
        raise At016EvidenceValidationError(
            "AT-016 unavailable OS evidence must be null."
        )
    validate_prohibited_content(
        value,
        prohibited_values=prohibited_values,
    )


def _canonical_document_bytes(document: Mapping[str, object]) -> bytes:
    try:
        rendered = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise At016EvidenceValidationError(
            "AT-016 evidence cannot be serialized canonically."
        ) from error
    return rendered.encode("utf-8") + b"\n"


def canonical_evidence_bytes(
    evidence: At016Evidence,
    *,
    prohibited_values: Iterable[str] = (),
) -> bytes:
    """Serialize one validated evidence value to its only canonical bytes."""

    document = evidence.to_document()
    validate_evidence_document(document, prohibited_values=prohibited_values)
    return _canonical_document_bytes(document)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise At016EvidenceValidationError(
                "AT-016 evidence contains a duplicate JSON key."
            )
        result[key] = value
    return result


def parse_evidence_bytes(
    data: bytes,
    *,
    prohibited_values: Iterable[str] = (),
) -> dict[str, object]:
    """Decode, duplicate-check, validate, and confirm exact canonical bytes."""

    if not isinstance(data, bytes) or not data.endswith(b"\n") or data.endswith(
        b"\n\n"
    ):
        raise At016EvidenceValidationError(
            "AT-016 evidence requires exactly one final LF."
        )
    try:
        text = data.decode("utf-8")
        document = json.loads(
            text[:-1],
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                At016EvidenceValidationError(
                    "AT-016 evidence contains a non-finite number."
                )
            ),
        )
    except At016EvidenceValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise At016EvidenceValidationError(
            "AT-016 evidence is not one valid UTF-8 JSON object."
        ) from error
    if not isinstance(document, dict):
        raise At016EvidenceValidationError(
            "AT-016 evidence root must be an object."
        )
    validate_evidence_document(document, prohibited_values=prohibited_values)
    if _canonical_document_bytes(document) != data:
        raise At016EvidenceValidationError(
            "AT-016 evidence bytes are not canonical."
        )
    return document


def evidence_filename(recorded_at_utc: str) -> str:
    """Derive the unique final filename from the validated evidence timestamp."""

    timestamp = _validate_timestamp(recorded_at_utc)
    compact = timestamp.translate(str.maketrans("", "", "-:."))
    return f"at-016-{compact}.json"


def _native_rename_no_replace(source: Path, destination: Path) -> None:
    """Publish with Linux renameat2(RENAME_NOREPLACE), never overwriting."""

    if sys.platform != "linux":
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise At016EvidenceCollisionError
    raise OSError(error_number, "atomic no-replace rename failed")


def write_evidence(
    directory: Path,
    evidence: At016Evidence,
    *,
    gate: At016Gate,
    prohibited_values: Iterable[str] = (),
) -> Path:
    """Write, close, reread, validate, and atomically publish one artifact."""

    if not gate.artifact_lifecycle_started:
        raise At016EvidenceLifecycleError(
            "AT-016 evidence lifecycle has not started."
        )
    temporary_path: Path | None = None
    try:
        private = tuple(prohibited_values)
        data = canonical_evidence_bytes(evidence, prohibited_values=private)
        output_directory = Path(directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        final_path = output_directory / evidence_filename(evidence.recorded_at_utc)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{final_path.stem}-",
            suffix=".tmp",
            dir=output_directory,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        reread_temporary = temporary_path.read_bytes()
        if reread_temporary != data:
            raise At016EvidenceValidationError(
                "AT-016 temporary evidence bytes changed."
            )
        parse_evidence_bytes(
            reread_temporary,
            prohibited_values=private,
        )
        _native_rename_no_replace(temporary_path, final_path)
        temporary_path = None
        reread_final = final_path.read_bytes()
        if reread_final != data:
            raise At016EvidenceValidationError(
                "AT-016 published evidence bytes changed."
            )
        parse_evidence_bytes(reread_final, prohibited_values=private)
        return final_path
    except At016EvidenceCollisionError:
        raise
    except Exception:
        raise At016EvidenceWriteError from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "ACCEPTANCE_ID",
    "EVIDENCE_SCHEMA_VERSION",
    "EVIDENCE_TOP_LEVEL_KEYS",
    "FIXTURE_VERSION",
    "LIMITATIONS",
    "MODEL_BASE_URL_VARIABLE",
    "MODEL_NAME_VARIABLE",
    "SMOKE_SENTINEL",
    "At016Evidence",
    "At016EvidenceCollisionError",
    "At016EvidenceLifecycleError",
    "At016EvidenceValidationError",
    "At016EvidenceWriteError",
    "At016Failure",
    "At016Gate",
    "At016ModelEvidence",
    "At016OsEvidence",
    "At016Prerequisites",
    "At016ProviderEvidence",
    "canonical_evidence_bytes",
    "collect_os_evidence",
    "evaluate_at_016_gate",
    "evidence_filename",
    "finalize_evidence",
    "format_recorded_at",
    "model_evidence",
    "parse_evidence_bytes",
    "project_transport_failure",
    "provider_evidence",
    "retain_first_failure",
    "validate_evidence_document",
    "validate_prohibited_content",
    "validated_prerequisites",
    "write_evidence",
]
