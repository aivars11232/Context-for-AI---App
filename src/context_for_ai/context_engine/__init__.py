"""Deterministic, infrastructure-independent context components."""

from context_for_ai.context_engine.clarification import (
    DeterministicClarificationBuilder,
)
from context_for_ai.context_engine.constraints import DeterministicConstraintEngine
from context_for_ai.context_engine.interpretation import (
    DeterministicInterpretationEngine,
)
from context_for_ai.context_engine.normalization import (
    NormalizedText,
    PhraseMatch,
    find_phrase_matches,
    normalize_capture,
    normalize_display_label,
    normalize_phrase,
    normalize_text,
    predicate_atom,
    split_action_object,
)
from context_for_ai.context_engine.reference_extraction import (
    DeterministicReferenceMentionExtractor,
    NamedItemDeclaration,
    parse_named_item_declaration,
)
from context_for_ai.context_engine.reference_resolution import (
    DeterministicReferenceResolver,
)

__all__ = [
    "DeterministicClarificationBuilder",
    "DeterministicConstraintEngine",
    "DeterministicInterpretationEngine",
    "DeterministicReferenceMentionExtractor",
    "DeterministicReferenceResolver",
    "NamedItemDeclaration",
    "NormalizedText",
    "PhraseMatch",
    "find_phrase_matches",
    "normalize_capture",
    "normalize_display_label",
    "normalize_phrase",
    "normalize_text",
    "parse_named_item_declaration",
    "predicate_atom",
    "split_action_object",
]
