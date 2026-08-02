"""Package foundation tests."""


def test_package_imports() -> None:
    import context_for_ai

    assert context_for_ai.__doc__ == "Context for AI local desktop application package."
