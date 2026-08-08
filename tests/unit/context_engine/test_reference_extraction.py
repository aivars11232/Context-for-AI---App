"""Focused tests for deterministic TASK-0008 mention extraction."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_for_ai.context_engine.normalization import normalize_phrase
from context_for_ai.context_engine.reference_extraction import (
    DeterministicReferenceMentionExtractor,
    parse_named_item_declaration,
)
from context_for_ai.domain.decisions import ReferenceMention
from context_for_ai.domain.entities import Entity, Message
from context_for_ai.domain.enums import EntityType, MessageRole
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import ReferenceMentionExtractionRequest
from context_for_ai.domain.value_objects import DomainId


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"30000000-0000-4000-8000-{number:012d}")


def message(text: str) -> Message:
    return Message(identifier(1), identifier(2), MessageRole.USER, text, NOW, 7)


def entity(
    number: int,
    display_name: str,
    *,
    entity_type: EntityType = EntityType.NAMED_ITEM,
    active: bool = True,
) -> Entity:
    native_id = identifier(100 + number)
    return Entity(
        identifier(number),
        entity_type,
        native_id,
        None,
        display_name,
        normalize_phrase(display_name),
        None,
        active,
        NOW,
        NOW,
    )


def extract(
    text: str,
    *,
    seeds: tuple[ReferenceMention, ...] = (),
    entities: tuple[Entity, ...] = (),
) -> tuple[ReferenceMention, ...]:
    return DeterministicReferenceMentionExtractor().extract(
        ReferenceMentionExtractionRequest(message(text), seeds, entities)
    )


def test_extractor_adds_only_complete_fixed_forms_in_source_order() -> None:
    source = (
        "Fix it, this app, that project, the topic, this task, same as before, "
        "the file; they those former."
    )

    mentions = extract(source)

    assert tuple(item.normalized_phrase for item in mentions) == (
        "it",
        "this app",
        "that project",
        "the topic",
        "this task",
        "same as before",
        "the file",
    )
    assert tuple(item.mention_ordinal for item in mentions) == tuple(range(7))
    assert all(
        source[item.start_offset : item.end_offset] == item.surface_text
        for item in mentions
    )


def test_extractor_matches_complete_inactive_unicode_name_with_exact_offsets() -> None:
    source = "Update CAFE\u0301   Architecture, not ArchitectureX."

    mentions = extract(
        source,
        entities=(entity(3, "CAFÉ Architecture", active=False),),
    )

    assert len(mentions) == 1
    assert mentions[0].surface_text == "CAFE\u0301   Architecture"
    assert mentions[0].normalized_phrase == "café architecture"
    assert mentions[0].qualifier_rule_id == f"reference-name:{identifier(3)}"


def test_shared_span_precedence_keeps_seed_then_registry_name_then_fixed_form() -> None:
    source = "same as before and this app"
    seed = ReferenceMention(
        0,
        "same as before",
        "same as before",
        "qualifier.prior-reference",
        0,
        14,
    )

    mentions = extract(
        source,
        seeds=(seed,),
        entities=(entity(4, "same as before"), entity(3, "this app")),
    )

    assert tuple(item.qualifier_rule_id for item in mentions) == (
        "qualifier.prior-reference",
        f"reference-name:{identifier(3)}",
    )
    assert mentions[0] is not seed
    assert seed.mention_ordinal == 0


def test_earlier_accepted_form_discards_later_overlapping_name() -> None:
    mentions = extract("the app", entities=(entity(3, "app"),))

    assert len(mentions) == 1
    assert mentions[0].normalized_phrase == "the app"
    assert mentions[0].qualifier_rule_id == "reference-form:the app"


def test_declaration_parser_normalizes_label_and_retains_call_this_target() -> None:
    source = '  CALL   THIS   "  CAFE\u0301   Board " \n'
    declaration = parse_named_item_declaration(source)

    assert declaration is not None
    assert declaration.command == "call this"
    assert declaration.display_name == "CAFÉ Board"
    assert declaration.normalized_name == "café board"
    assert source[
        declaration.target_start_offset : declaration.target_end_offset
    ] == "THIS"

    mentions = extract(source, entities=(entity(3, "CAFÉ Board"),))
    assert tuple(item.normalized_phrase for item in mentions) == ("this",)
    assert mentions[0].surface_text == "THIS"


def test_name_declaration_excludes_quoted_label_and_has_no_synthetic_mention() -> None:
    source = 'name "this app"'
    declaration = parse_named_item_declaration(source)

    assert declaration is not None
    assert extract(source, entities=(entity(3, "this app"),)) == ()


@pytest.mark.parametrize(
    "source",
    (
        'name ""',
        'name "   "',
        'name "bad\x00label"',
        'name "embedded " quote"',
        'please name "architecture"',
        'name"architecture"',
    ),
)
def test_invalid_or_non_whole_message_declarations_are_not_parsed(source: str) -> None:
    assert parse_named_item_declaration(source) is None


def test_invalid_seed_normalization_is_rejected_without_mutation() -> None:
    seed = ReferenceMention(0, "same as before", "wrong", "seed", 0, 14)

    with pytest.raises(LifecycleInvariantError, match="normalized phrase"):
        extract("same as before", seeds=(seed,))
    assert seed.normalized_phrase == "wrong"


def test_unsupported_forms_and_no_reference_return_empty_sequence() -> None:
    assert extract("They changed those former files and architecture.") == ()
    assert extract("") == ()
