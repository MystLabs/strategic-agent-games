"""Registry of game ids to Game implementations."""

import threading

from arena.spec import GameSpec

from arena.games.base import Game

_registry: dict[str, Game] = {}
_lock = threading.Lock()


def register_game(game: Game) -> None:
    """Register a game by its spec.game_id."""
    with _lock:
        _registry[game.spec().game_id] = game


def get_game_spec(game_id: str) -> GameSpec | None:
    """Return the spec for a game by id, or None if not registered."""
    with _lock:
        g = _registry.get(game_id)
    return g.spec() if g else None


def get_game(game_id: str) -> Game | None:
    """Return the Game instance for game_id, or None."""
    with _lock:
        return _registry.get(game_id)


def list_game_ids() -> list[str]:
    """Return all registered game ids."""
    with _lock:
        return list(_registry.keys())
