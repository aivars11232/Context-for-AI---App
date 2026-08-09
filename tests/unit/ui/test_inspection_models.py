"""Read-only primitive Qt models for TASK-0016 context inspection."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel

from context_for_ai.ui.presentation import (
    ContextInspectionPresentationView,
    InspectionCollectionPresentation,
    InspectionListItemPresentation,
    InspectionScalarPresentation,
    InspectionSectionPresentation,
)
from context_for_ai.ui.shell import _InspectionSectionListModel


SECTION_IDENTITIES = (
    ("contextInspectionSectionTarget", "Inspected request"),
    ("contextInspectionSectionActiveState", "Active state"),
    ("contextInspectionSectionInterpretation", "Interpretation"),
    ("contextInspectionSectionReferences", "References"),
    ("contextInspectionSectionConstraints", "Constraints and conflicts"),
    ("contextInspectionSectionMemories", "Retrieved memories"),
    ("contextInspectionSectionConfidence", "Confidence"),
    ("contextInspectionSectionValidation", "Validation"),
    ("contextInspectionSectionFinalStatus", "Final status"),
)


def role(model: QAbstractListModel, name: str) -> int:
    return next(
        key
        for key, value in model.roleNames().items()
        if bytes(value).decode("ascii") == name
    )


def test_recursive_inspection_models_expose_only_strings_and_child_models() -> None:
    scalar = InspectionScalarPresentation("Request", "Request 3")
    nested_scalar = InspectionScalarPresentation("Rule", "Keep exact text")
    item = InspectionListItemPresentation(
        "Constraint 1: Hard, Applied",
        (nested_scalar,),
    )
    collection = InspectionCollectionPresentation(
        "contextInspectionConstraints",
        "Constraints",
        "AVAILABLE",
        "",
        (item,),
    )
    sections = tuple(
        InspectionSectionPresentation(
            accessible_id,
            accessible_name,
            (scalar,) if index == 0 else (),
            (collection,) if index == 4 else (),
        )
        for index, (accessible_id, accessible_name) in enumerate(SECTION_IDENTITIES)
    )
    model = _InspectionSectionListModel()

    model.replace(ContextInspectionPresentationView("PROCESSING", sections))

    assert model.rowCount() == 9
    assert model.data(model.index(0, 0), role(model, "accessibleId")) == (
        "contextInspectionSectionTarget"
    )
    scalars = model.data(model.index(0, 0), role(model, "scalars"))
    assert isinstance(scalars, QAbstractListModel)
    assert scalars.data(scalars.index(0, 0), role(scalars, "label")) == "Request"
    assert scalars.data(
        scalars.index(0, 0),
        role(scalars, "accessibleName"),
    ) == "Request: Request 3"

    collections = model.data(model.index(4, 0), role(model, "collections"))
    assert isinstance(collections, QAbstractListModel)
    assert collections.data(
        collections.index(0, 0),
        role(collections, "availability"),
    ) == "AVAILABLE"
    items = collections.data(collections.index(0, 0), role(collections, "items"))
    assert isinstance(items, QAbstractListModel)
    assert items.data(
        items.index(0, 0),
        role(items, "accessibleName"),
    ) == "Constraint 1: Hard, Applied"
    item_scalars = items.data(items.index(0, 0), role(items, "scalars"))
    assert isinstance(item_scalars, QAbstractListModel)
    assert item_scalars.data(
        item_scalars.index(0, 0),
        role(item_scalars, "displayText"),
    ) == "Keep exact text"

    for current in (model, scalars, collections, items, item_scalars):
        for row in range(current.rowCount()):
            index = current.index(row, 0)
            assert all(
                value is None
                or isinstance(value, (str, QAbstractListModel))
                for role_id in current.roleNames()
                if (value := current.data(index, role_id)) is not None
            )


def test_replacing_or_clearing_model_removes_all_prior_rows() -> None:
    model = _InspectionSectionListModel()
    sections = tuple(
        InspectionSectionPresentation(identity, name, (), ())
        for identity, name in SECTION_IDENTITIES
    )

    model.replace(ContextInspectionPresentationView("SUCCEEDED", sections))
    assert model.rowCount() == 9
    model.replace(None)
    assert model.rowCount() == 0

