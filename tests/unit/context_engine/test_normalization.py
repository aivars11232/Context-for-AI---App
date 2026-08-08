"""Deterministic source-preserving normalization tests for TASK-0007."""

from __future__ import annotations

import pytest

from context_for_ai.context_engine.normalization import (
    find_phrase_matches,
    normalize_capture,
    normalize_display_label,
    normalize_phrase,
    normalize_text,
    predicate_atom,
    split_action_object,
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
