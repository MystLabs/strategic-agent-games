"""Pytest fixtures: register games so get_game works in tests."""

import pytest

from arena.games.builtins import ensure_builtins_registered


@pytest.fixture(scope="session", autouse=True)
def register_builtin_games():
    """Register ultimatum and auction so runner get_turn_state can resolve games."""
    ensure_builtins_registered()
