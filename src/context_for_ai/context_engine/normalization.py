"""Source-preserving deterministic text normalization for TASK-0007."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from context_for_ai.domain.errors import LifecycleInvariantError


@dataclass(frozen=True, slots=True)
class PhraseMatch:
    """One normalized phrase occurrence mapped to exact original source offsets."""

    normalized_phrase: str
    matched_text: str
    start_offset: int
    end_offset: int
    normalized_start: int
    normalized_end: int


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalized text plus one original half-open span per normalized character."""

    source: str
    text: str
    source_spans: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.source_spans):
            raise LifecycleInvariantError(
                "Normalized text requires one source span per character."
            )

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        if start < 0 or end <= start or end > len(self.source_spans):
            raise LifecycleInvariantError("Normalized source span is out of range.")
        return self.source_spans[start][0], self.source_spans[end - 1][1]


def _clusters(source: str) -> tuple[tuple[str, int, int], ...]:
    clusters: list[tuple[str, int, int]] = []
    start = 0
    current = ""
    for index, character in enumerate(source):
        if current and unicodedata.combining(character) == 0:
            clusters.append((current, start, index))
            current = character
            start = index
        else:
            if not current:
                start = index
            current += character
    if current:
        clusters.append((current, start, len(source)))
    return tuple(clusters)


def normalize_text(source: str) -> NormalizedText:
    """Normalize text while preserving source offsets for every output character."""

    if not isinstance(source, str):
        raise LifecycleInvariantError("Text normalization requires source text.")
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    pending_space: tuple[int, int] | None = None

    for cluster, source_start, source_end in _clusters(source):
        normalized_cluster = unicodedata.normalize("NFC", cluster).casefold()
        for character in normalized_cluster:
            if character.isspace():
                if characters:
                    pending_space = (
                        source_start
                        if pending_space is None
                        else pending_space[0],
                        source_end,
                    )
                continue
            if pending_space is not None:
                characters.append(" ")
                spans.append(pending_space)
                pending_space = None
            characters.append(character)
            spans.append((source_start, source_end))

    return NormalizedText(source, "".join(characters), tuple(spans))


def normalize_phrase(phrase: str) -> str:
    """Return the canonical phrase form used by validated rule tables."""

    return normalize_text(phrase).text


def _is_word_character(character: str) -> bool:
    return character.isalnum()


def find_phrase_matches(
    normalized: NormalizedText,
    phrase: str,
) -> tuple[PhraseMatch, ...]:
    """Return all word-bounded occurrences in normalized source order."""

    canonical_phrase = normalize_phrase(phrase)
    if not canonical_phrase:
        raise LifecycleInvariantError("A matched phrase must be non-empty.")
    matches: list[PhraseMatch] = []
    search_start = 0
    while True:
        start = normalized.text.find(canonical_phrase, search_start)
        if start < 0:
            break
        end = start + len(canonical_phrase)
        left_ok = (
            not _is_word_character(canonical_phrase[0])
            or start == 0
            or not _is_word_character(normalized.text[start - 1])
        )
        right_ok = (
            not _is_word_character(canonical_phrase[-1])
            or end == len(normalized.text)
            or not _is_word_character(normalized.text[end])
        )
        if left_ok and right_ok:
            source_start, source_end = normalized.source_span(start, end)
            matches.append(
                PhraseMatch(
                    canonical_phrase,
                    normalized.source[source_start:source_end],
                    source_start,
                    source_end,
                    start,
                    end,
                )
            )
        search_start = start + 1
    return tuple(matches)


def normalize_capture(value: str, *, remove_determiners: bool = True) -> str:
    """Return lower-case alphanumeric capture tokens in canonical spacing."""

    normalized = normalize_phrase(value)
    tokens: list[str] = []
    token: list[str] = []
    for character in normalized:
        if character.isalnum():
            token.append(character)
        elif token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    if remove_determiners:
        tokens = [item for item in tokens if item not in {"a", "an", "the"}]
    return " ".join(tokens)


def predicate_atom(value: str) -> str:
    """Encode a normalized capture as an uppercase underscore predicate atom."""

    normalized = normalize_capture(value, remove_determiners=False)
    if not normalized:
        raise LifecycleInvariantError("A predicate atom requires captured text.")
    return "_".join(normalized.split()).upper()


def split_action_object(value: str) -> tuple[str, str]:
    """Split one canonical capture into its first action and remaining object."""

    normalized = normalize_capture(value)
    action, separator, object_text = normalized.partition(" ")
    if not separator or not action or not object_text:
        raise LifecycleInvariantError(
            "A constraint capture requires an explicit action and object."
        )
    return action, object_text


__all__ = [
    "NormalizedText",
    "PhraseMatch",
    "find_phrase_matches",
    "normalize_capture",
    "normalize_phrase",
    "normalize_text",
    "predicate_atom",
    "split_action_object",
]
