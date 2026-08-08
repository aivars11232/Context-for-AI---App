"""Pure deterministic TASK-0008 reference-mention extraction."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from context_for_ai.context_engine.normalization import (
    find_phrase_matches,
    normalize_display_label,
    normalize_phrase,
    normalize_text,
)
from context_for_ai.domain.decisions import ReferenceMention
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import ReferenceMentionExtractionRequest


_FIXED_FORMS = (
    "it",
    "this",
    "that",
    "the app",
    "this app",
    "that app",
    "the project",
    "this project",
    "that project",
    "the topic",
    "this topic",
    "that topic",
    "the task",
    "this task",
    "that task",
    "same as before",
    "the file",
    "this file",
    "that file",
)
_SEED_PRECEDENCE = 0
_NAME_PRECEDENCE = 1
_FIXED_PRECEDENCE = 2


@dataclass(frozen=True, slots=True)
class NamedItemDeclaration:
    """One valid whole-message named-item declaration and exact source spans."""

    command: str
    display_name: str
    normalized_name: str
    label_start_offset: int
    label_end_offset: int
    target_start_offset: int | None
    target_end_offset: int | None


@dataclass(frozen=True, slots=True)
class _MentionCandidate:
    surface_text: str
    normalized_phrase: str
    rule_id: str
    start_offset: int
    end_offset: int
    precedence: int


def _trimmed_bounds(source: str) -> tuple[int, int]:
    start = 0
    end = len(source)
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return start, end


def parse_named_item_declaration(source: str) -> NamedItemDeclaration | None:
    """Parse exactly one canonical whole-message named-item declaration."""

    if not isinstance(source, str):
        raise LifecycleInvariantError("Named-item declaration parsing requires text.")
    outer_start, outer_end = _trimmed_bounds(source)
    if outer_start == outer_end:
        return None
    candidate = source[outer_start:outer_end]
    quote_start = candidate.find('"')
    if (
        quote_start <= 0
        or candidate[-1] != '"'
        or candidate.count('"') != 2
        or not candidate[quote_start - 1].isspace()
    ):
        return None

    command = normalize_phrase(candidate[:quote_start])
    if command not in {"name", "call this"}:
        return None
    raw_label = candidate[quote_start + 1 : -1]
    if any(unicodedata.category(character) == "Cc" for character in raw_label):
        return None
    display_name = normalize_display_label(raw_label)
    if not display_name:
        return None

    label_start = outer_start + quote_start + 1
    label_end = outer_end - 1
    target_start: int | None = None
    target_end: int | None = None
    if command == "call this":
        prefix = normalize_text(candidate[:quote_start])
        target_matches = find_phrase_matches(prefix, "this")
        if len(target_matches) != 1:
            return None
        target_start = outer_start + target_matches[0].start_offset
        target_end = outer_start + target_matches[0].end_offset

    return NamedItemDeclaration(
        command,
        display_name,
        normalize_phrase(display_name),
        label_start,
        label_end,
        target_start,
        target_end,
    )


def _overlaps(left: _MentionCandidate, start: int, end: int) -> bool:
    return left.start_offset < end and start < left.end_offset


class DeterministicReferenceMentionExtractor:
    """Merge immutable seed evidence with the finite TASK-0008 forms."""

    def extract(
        self,
        request: ReferenceMentionExtractionRequest,
    ) -> tuple[ReferenceMention, ...]:
        source = request.message.original_text
        normalized = normalize_text(source)
        declaration = parse_named_item_declaration(source)
        candidates: list[_MentionCandidate] = []

        for seed in request.seed_mentions:
            if normalize_phrase(seed.surface_text) != seed.normalized_phrase:
                raise LifecycleInvariantError(
                    "Seed reference normalized phrase must match its source surface."
                )
            candidates.append(
                _MentionCandidate(
                    seed.surface_text,
                    seed.normalized_phrase,
                    seed.qualifier_rule_id,
                    seed.start_offset,
                    seed.end_offset,
                    _SEED_PRECEDENCE,
                )
            )

        for entity in request.scoped_entities:
            if normalize_phrase(entity.display_name) != entity.normalized_name:
                raise LifecycleInvariantError(
                    "Scoped entity normalized name must match its display name."
                )
            for match in find_phrase_matches(normalized, entity.normalized_name):
                candidates.append(
                    _MentionCandidate(
                        match.matched_text,
                        match.normalized_phrase,
                        f"reference-name:{entity.id}",
                        match.start_offset,
                        match.end_offset,
                        _NAME_PRECEDENCE,
                    )
                )

        for form in _FIXED_FORMS:
            for match in find_phrase_matches(normalized, form):
                candidates.append(
                    _MentionCandidate(
                        match.matched_text,
                        match.normalized_phrase,
                        f"reference-form:{form}",
                        match.start_offset,
                        match.end_offset,
                        _FIXED_PRECEDENCE,
                    )
                )

        if declaration is not None:
            candidates = [
                candidate
                for candidate in candidates
                if not _overlaps(
                    candidate,
                    declaration.label_start_offset,
                    declaration.label_end_offset,
                )
            ]

        candidates.sort(
            key=lambda candidate: (
                candidate.start_offset,
                -(candidate.end_offset - candidate.start_offset),
                candidate.precedence,
                candidate.rule_id,
                candidate.end_offset,
            )
        )
        accepted: list[_MentionCandidate] = []
        for candidate in candidates:
            if any(
                _overlaps(
                    candidate,
                    accepted_candidate.start_offset,
                    accepted_candidate.end_offset,
                )
                for accepted_candidate in accepted
            ):
                continue
            accepted.append(candidate)

        accepted.sort(
            key=lambda candidate: (
                candidate.start_offset,
                candidate.end_offset,
                candidate.rule_id,
            )
        )
        return tuple(
            ReferenceMention(
                ordinal,
                candidate.surface_text,
                candidate.normalized_phrase,
                candidate.rule_id,
                candidate.start_offset,
                candidate.end_offset,
            )
            for ordinal, candidate in enumerate(accepted)
        )


__all__ = [
    "DeterministicReferenceMentionExtractor",
    "NamedItemDeclaration",
    "parse_named_item_declaration",
]
