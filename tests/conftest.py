"""Shared pytest configuration.

The suite mocks the agent everywhere (see CLAUDE.md), so it runs green on a
machine with neither `claude` nor `agy` installed. A test that genuinely needs
one of those CLIs on PATH must say so with `@pytest.mark.requires_cli("claude")`
— it is then skipped, not failed, where the executable is missing.
"""

import shutil

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_cli(*names): skip unless every named executable is on PATH.",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    for mark in item.iter_markers(name="requires_cli"):
        for name in mark.args:
            if shutil.which(name) is None:
                pytest.skip(f"{name} is not on PATH")
