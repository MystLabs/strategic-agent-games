"""Base interface for games: spec + optional step/outcome logic."""

from typing import Any

from arena.core.match import Match, MatchStatus
from arena.games.utils import messages_visible_to, build_allowed_actions
from arena.spec import GameSpec, TurnOrder
from arena.types import Action, ActionResult, TurnState
from arena.core.runner import action_error, ActionError


class Game:
    """Abstract game: provides spec and (when implemented) transition and outcome logic."""

    # Payload fields that are private to the acting agent and should be redacted
    # in logs and dashboard.  Override in subclasses, e.g. {"my_valuation"}.
    private_payload_keys: frozenset[str] = frozenset()

    def spec(self) -> GameSpec:
        """Return the game specification."""
        raise NotImplementedError

    def compute_turn_state(self, match: Match, agent_id: str) -> TurnState | None:
        """Build TurnState for this agent from current match state. None if not this game."""
        raise NotImplementedError("compute_turn_state: implement per game")

    def apply_action(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        """Apply action; update match.game_state and match status/outcome. Return ActionResult."""
        raise NotImplementedError("apply_action: implement per game")

    def compute_outcome(self, match: Match) -> dict[str, Any] | None:
        """If game is over, return outcome dict (e.g. payoffs). Otherwise None."""
        raise NotImplementedError("compute_outcome: implement per game")

    @classmethod
    def from_params(cls, game_params: dict[str, Any], agent_ids: list[str]) -> "Game":
        """Create a game instance from dashboard/API parameters.

        Override in subclasses to map flat parameter dicts (e.g. from the web UI)
        to constructor arguments.  The default implementation ignores params
        and creates a default instance.
        """
        return cls()

    def get_metadata(self) -> dict[str, Any]:
        """Return game metadata for logging. Override in subclasses."""
        s = self.spec()
        return {"game_id": s.game_id, "name": s.name}

    # --- Shared helpers for subclasses ---

    def _not_running_turn_state(self, match: Match, agent_id: str) -> TurnState:
        """Build a TurnState for a match that is not running (finished/waiting)."""
        only_agent = match.agent_ids[0] if match.agent_ids else None
        return TurnState(
            match_id=match.match_id,
            game_id=match.game_id,
            agent_id=agent_id,
            phase="waiting_for_players",
            is_my_turn=False,
            current_turn_agent_id=only_agent,
            game_state={},
            messages=messages_visible_to(match.messages, agent_id),
            allowed_actions=[],
            game_over=(match.status == MatchStatus.FINISHED),
            outcome=match.outcome,
        )

    def _check_apply_preconditions(
        self, match: Match, agent_id: str, expected_game_id: str,
    ) -> ActionResult | None:
        """Check common apply_action preconditions. Returns an error ActionResult or None if OK."""
        if match.game_id != expected_game_id:
            return action_error(ActionError.MATCH_NOT_RUNNING, f"Not a {expected_game_id} match")
        if match.status != MatchStatus.RUNNING:
            return action_error(ActionError.MATCH_NOT_RUNNING, "Match is not running")
        return None

    @staticmethod
    def _advance_turn(match: Match) -> None:
        """Advance turn index to the next agent (wrapping around)."""
        n = len(match.agent_ids)
        if n == 0:
            return
        match.current_turn_index = (match.current_turn_index + 1) % n

    def _get_phase_and_turn_info(self, match: Match, agent_id: str) -> tuple[str, str, bool]:
        """Get current phase name, current turn agent ID, and is_my_turn.

        Returns (phase_name, current_turn_agent_id, is_my_turn).
        """
        spec = match.spec
        phase = spec.phases[match.current_phase_index] if spec.phases else None
        phase_name = phase.name if phase else "unknown"
        n = len(match.agent_ids)
        idx = match.current_turn_index % n if n else 0
        current_turn_agent_id = match.agent_ids[idx] if n else ""
        is_random = phase is not None and phase.turn_order == TurnOrder.RANDOM
        is_my_turn = True if is_random else (agent_id == current_turn_agent_id)
        return phase_name, current_turn_agent_id, is_my_turn
