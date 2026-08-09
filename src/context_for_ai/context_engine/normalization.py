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


@dataclass(frozen=True, slots=True)
class NormalizedWordToken:
    """One canonical retrieval word token mapped to its smallest source span."""

    text: str
    source_start: int
    source_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise LifecycleInvariantError("A normalized word token requires text.")
        if (
            not isinstance(self.source_start, int)
            or isinstance(self.source_start, bool)
            or self.source_start < 0
            or not isinstance(self.source_end, int)
            or isinstance(self.source_end, bool)
            or self.source_end <= self.source_start
        ):
            raise LifecycleInvariantError(
                "A normalized word token requires a valid source span."
            )


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    """One trimmed non-empty canonical candidate sentence source span."""

    ordinal: int
    source_start: int
    source_end: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ordinal, int)
            or isinstance(self.ordinal, bool)
            or self.ordinal < 0
            or not isinstance(self.source_start, int)
            or isinstance(self.source_start, bool)
            or self.source_start < 0
            or not isinstance(self.source_end, int)
            or isinstance(self.source_end, bool)
            or self.source_end <= self.source_start
        ):
            raise LifecycleInvariantError("SentenceSpan fields are out of range.")


def _clusters(source: str) -> tuple[tuple[str, int, int], ...]:
    clusters: list[tuple[str, int, int]] = []
    start = 0
    current = ""
    for index, character in enumerate(source):
        interacts = bool(current) and (
            unicodedata.combining(character) != 0
            or unicodedata.normalize("NFC", current + character)
            != unicodedata.normalize("NFC", current)
            + unicodedata.normalize("NFC", character)
        )
        if current and not interacts:
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


def normalize_casefolded_source(source: str) -> NormalizedText:
    """Apply NFC and case-folding without rewriting punctuation or whitespace."""

    if not isinstance(source, str):
        raise LifecycleInvariantError("Unicode normalization requires source text.")
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    for cluster, source_start, source_end in _clusters(source):
        for character in unicodedata.normalize("NFC", cluster).casefold():
            characters.append(character)
            spans.append((source_start, source_end))
    return NormalizedText(source, "".join(characters), tuple(spans))


def normalize_text(source: str) -> NormalizedText:
    """Normalize text while preserving source offsets for every output character."""

    if not isinstance(source, str):
        raise LifecycleInvariantError("Text normalization requires source text.")
    normalized_source = normalize_casefolded_source(source)
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    pending_space: tuple[int, int] | None = None

    for character, (source_start, source_end) in zip(
        normalized_source.text,
        normalized_source.source_spans,
        strict=True,
    ):
        if character.isspace():
            if characters:
                pending_space = (
                    source_start if pending_space is None else pending_space[0],
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


def normalize_word_tokens(source: str) -> tuple[NormalizedWordToken, ...]:
    """Return canonical punctuation-deleting words with exact source offsets."""

    normalized = normalize_casefolded_source(source)
    tokens: list[NormalizedWordToken] = []
    characters: list[str] = []
    contributing_spans: list[tuple[int, int]] = []

    def finish_token() -> None:
        if characters:
            tokens.append(
                NormalizedWordToken(
                    "".join(characters),
                    contributing_spans[0][0],
                    contributing_spans[-1][1],
                )
            )
            characters.clear()
            contributing_spans.clear()

    for character, source_span in zip(
        normalized.text,
        normalized.source_spans,
        strict=True,
    ):
        if unicodedata.category(character).startswith("P"):
            continue
        if character.isspace():
            finish_token()
            continue
        characters.append(character)
        contributing_spans.append(source_span)
    finish_token()
    return tuple(tokens)


def normalize_words(source: str) -> str:
    """Return canonical retrieval word content joined by one ASCII space."""

    return " ".join(token.text for token in normalize_word_tokens(source))


def find_casefolded_literal_spans(
    source: str,
    literal: str,
) -> tuple[tuple[int, int], ...]:
    """Return every overlapping NFC/case-folded literal source occurrence."""

    normalized = normalize_casefolded_source(source)
    if not isinstance(literal, str):
        raise LifecycleInvariantError("Literal matching requires text.")
    canonical_literal = unicodedata.normalize("NFC", literal).casefold()
    if not canonical_literal:
        raise LifecycleInvariantError("Literal matching requires a non-empty literal.")
    spans: list[tuple[int, int]] = []
    search_start = 0
    while True:
        start = normalized.text.find(canonical_literal, search_start)
        if start < 0:
            break
        end = start + len(canonical_literal)
        spans.append(normalized.source_span(start, end))
        search_start = start + 1
    return tuple(spans)


def split_sentence_spans(source: str) -> tuple[SentenceSpan, ...]:
    """Split exact candidate text using the TASK-0013 sentence grammar."""

    if not isinstance(source, str):
        raise LifecycleInvariantError("Sentence splitting requires source text.")
    raw_spans: list[tuple[int, int]] = []
    segment_start = 0
    index = 0
    source_length = len(source)

    def add_span(start: int, end: int) -> None:
        while start < end and source[start].isspace():
            start += 1
        while end > start and source[end - 1].isspace():
            end -= 1
        if start < end:
            raw_spans.append((start, end))

    while index < source_length:
        character = source[index]
        if character in {"\r", "\n"}:
            add_span(segment_start, index)
            index += 2 if character == "\r" and index + 1 < source_length and source[index + 1] == "\n" else 1
            while index < source_length and source[index].isspace():
                index += 1
            segment_start = index
            continue
        if character in ".?!" and (
            index + 1 == source_length or source[index + 1].isspace()
        ):
            add_span(segment_start, index + 1)
            index += 1
            while index < source_length and source[index].isspace():
                index += 1
            segment_start = index
            continue
        index += 1
    add_span(segment_start, source_length)
    return tuple(
        SentenceSpan(ordinal, start, end)
        for ordinal, (start, end) in enumerate(raw_spans)
    )


def normalize_phrase(phrase: str) -> str:
    """Return the canonical phrase form used by validated rule tables."""

    return normalize_text(phrase).text


def normalize_display_label(label: str) -> str:
    """Return a case-preserving NFC label with canonical whitespace."""

    if not isinstance(label, str):
        raise LifecycleInvariantError("Display-label normalization requires text.")
    return " ".join(unicodedata.normalize("NFC", label).split())


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
    "NormalizedWordToken",
    "PhraseMatch",
    "SentenceSpan",
    "find_casefolded_literal_spans",
    "find_phrase_matches",
    "normalize_capture",
    "normalize_display_label",
    "normalize_phrase",
    "normalize_casefolded_source",
    "normalize_text",
    "normalize_word_tokens",
    "normalize_words",
    "predicate_atom",
    "split_action_object",
    "split_sentence_spans",
]
