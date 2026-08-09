"""Deterministic source-preserving normalization tests for TASK-0007."""

from __future__ import annotations

import pytest

from context_for_ai.context_engine.normalization import (
    find_casefolded_literal_spans,
    find_phrase_matches,
    normalize_capture,
    normalize_display_label,
    normalize_phrase,
    normalize_text,
    normalize_word_tokens,
    normalize_words,
    predicate_atom,
    split_action_object,
    split_sentence_spans,
)
from context_for_ai.domain.errors import LifecycleInvariantError


def test_unicode_nfc_casefold_whitespace_and_offsets_are_source_preserving() -> None:
    source = "  CAFE\u0301   Straße\tPLAN planet  "
    normalized = normalize_text(source)

    assert normalized.text == "café strasse plan planet"
    cafe = find_phrase_matches(normalized, "café")[0]
    street = find_phrase_matches(normalized, "strasse")[0]
    plan = find_phrase_matches(normalized, "plan")[0]
    assert source[cafe.start_offset : cafe.end_offset] == "CAFE\u0301"
    assert source[street.start_offset : street.end_offset] == "Straße"
    assert source[plan.start_offset : plan.end_offset] == "PLAN"


def test_unicode_word_boundaries_do_not_match_inside_larger_words() -> None:
    normalized = normalize_text("plan planet éplan plané plan")

    matches = find_phrase_matches(normalized, "plan")

    assert tuple(match.matched_text for match in matches) == ("plan", "plan")


def test_overlapping_phrases_remain_observable_for_deterministic_ranking() -> None:
    normalized = normalize_text("Write a text prompt")

    longer = find_phrase_matches(normalized, "text prompt")
    shorter = find_phrase_matches(normalized, "prompt")

    assert longer[0].start_offset < shorter[0].start_offset
    assert longer[0].end_offset == shorter[0].end_offset


def test_capture_and_predicate_normalization_are_exact() -> None:
    assert normalize_capture(" Remove   the blue-line! ") == "remove blue line"
    assert predicate_atom("blue line") == "BLUE_LINE"
    assert split_action_object("Remove the blue line") == ("remove", "blue line")
    with pytest.raises(LifecycleInvariantError, match="action and object"):
        split_action_object("remove")


def test_display_label_normalization_preserves_case_and_canonicalizes_unicode() -> None:
    source = "  CAFE\u0301\t  Architecture\nBoard  "

    assert normalize_display_label(source) == "CAFÉ Architecture Board"
    assert normalize_phrase(source) == "café architecture board"
    assert normalize_display_label(" \t\n ") == ""
    with pytest.raises(LifecycleInvariantError, match="requires text"):
        normalize_display_label(None)  # type: ignore[arg-type]


def test_retrieval_words_delete_punctuation_and_preserve_exact_scalar_offsets() -> None:
    source = "  CAFE\u0301\tStraße foo-bar\u2003C++  "

    tokens = normalize_word_tokens(source)

    assert tuple(token.text for token in tokens) == (
        "café",
        "strasse",
        "foobar",
        "c++",
    )
    assert tuple(source[token.source_start : token.source_end] for token in tokens) == (
        "CAFE\u0301",
        "Straße",
        "foo-bar",
        "C++",
    )
    assert normalize_words(source) == "café strasse foobar c++"
    assert normalize_words("---…") == ""


def test_casefolded_literal_matching_preserves_overlaps_and_source_mapping() -> None:
    assert find_casefolded_literal_spans("aaaa", "aa") == (
        (0, 2),
        (1, 3),
        (2, 4),
    )
    assert find_casefolded_literal_spans("Straße", "SS") == ((4, 5),)
    with pytest.raises(LifecycleInvariantError, match="non-empty literal"):
        find_casefolded_literal_spans("text", "")


def test_sentence_spans_follow_exact_line_and_terminator_grammar() -> None:
    source = "  One?!  Two\r\n  Three.\n\nFour?Five!  "

    sentences = split_sentence_spans(source)

    assert tuple(sentence.ordinal for sentence in sentences) == (0, 1, 2, 3)
    assert tuple(
        source[sentence.source_start : sentence.source_end]
        for sentence in sentences
    ) == ("One?!", "Two", "Three.", "Four?Five!")
    assert split_sentence_spans(" \r\n\t ") == ()
    with pytest.raises(LifecycleInvariantError, match="requires source text"):
        split_sentence_spans(None)  # type: ignore[arg-type]
