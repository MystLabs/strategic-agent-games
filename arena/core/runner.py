"""Match runner: advances turns, applies actions, computes outcomes."""

import copy
import time
import uuid

from arena.spec import GameSpec
from arena.spec.schema import TurnOrder
from arena.types import (
    Action,
    ActionError,
    ActionResult,
    Message,
    MessageScope,
    TurnState,
    action_error,
    action_ok,
)

from arena.core.match import Match, MatchStatus


def create_match(match_id: str, game_id: str, spec: GameSpec, agent_ids: list[str]) -> Match:
    """Create a new match (WAITING until min_agents have joined, then RUNNING)."""
    game_state = copy.deepcopy(spec.initial_game_state)
    min_agents = getattr(spec, "min_agents", 1)
    status = MatchStatus.RUNNING if len(agent_ids) >= min_agents else MatchStatus.WAITING
    return Match(
        match_id=match_id,
        game_id=game_id,
        spec=spec,
        agent_ids=list(agent_ids),
        status=status,
        current_phase_index=0,
        current_round=0,
        current_turn_index=0,
        game_state=game_state,
        messages=[],
        outcome=None,
    )


def get_turn_state(match: Match, agent_id: str) -> TurnState | None:
    """Return the turn state for the given agent (what they see and can do)."""
    from arena.games import get_game

    game = get_game(match.game_id)
    if game is None:
        return None
    return game.compute_turn_state(match, agent_id)


def apply_message(match: Match, sender_id: str, scope: str, content: str, to_agent_ids: list[str] | None) -> ActionResult:
    """Record a public or private message. Messages do NOT advance turns."""
    if match.status != MatchStatus.RUNNING:
        return action_error(ActionError.MATCH_NOT_RUNNING, "Match is not running")
    if sender_id not in match.agent_ids:
        return action_error(ActionError.AGENT_NOT_IN_MATCH, f"Agent {sender_id} is not in this match")
    scope_enum = MessageScope.PUBLIC if scope == "public" else MessageScope.PRIVATE
    to_list = list(to_agent_ids) if to_agent_ids else []
    msg = Message(
        message_id=uuid.uuid4().hex,
        sender_id=sender_id,
        scope=scope_enum,
        content=content,
        to_agent_ids=to_list,
        timestamp_ns=time.time_ns(),
    )
    match.messages.append(msg)
    return action_ok()


def apply_action(match: Match, agent_id: str, action: Action) -> ActionResult:
    """Apply a game action (e.g. submit_offer, accept); may advance turn/phase and set outcome."""
    from arena.games import get_game

    game = get_game(match.game_id)
    if game is None:
        return action_error(ActionError.MATCH_NOT_FOUND, f"No game registered for {match.game_id}")
    result = game.apply_action(match, agent_id, action)
    if not result.ok:
        return result
    if match.status == MatchStatus.FINISHED:
        return result
    outcome = game.compute_outcome(match)
    if outcome is not None:
        match.outcome = outcome
        match.status = MatchStatus.FINISHED
    return result
