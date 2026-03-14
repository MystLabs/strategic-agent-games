"""Tests for ultimatum game: submit_offer, accept, reject, outcome — N-player + turn_order."""

from arena.core.match import MatchStatus
from arena.core.runner import apply_action, create_match, get_turn_state
from arena.games import get_game, get_game_spec
from arena.games.ultimatum import UltimatumGame
from arena.spec.schema import TurnOrder
from arena.types import Action


# ---------------------------------------------------------------------------
# 2-player (classic) tests — updated for shares dict format
# ---------------------------------------------------------------------------


def test_ultimatum_submit_offer_updates_game_state():
    """submit_offer sets current_offer, last_offer_by, and action_history; advances turn."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    result = apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 60, "b": 40}}))
    assert result.ok is True
    assert match.game_state["current_offer"] == {"a": 60.0, "b": 40.0}
    assert match.game_state["last_offer_by"] == "a"
    assert match.current_turn_index == 1
    assert len(match.game_state["action_history"]) == 1
    assert match.game_state["action_history"][0] == {"agent_id": "a", "action": "submit_offer", "shares": {"a": 60.0, "b": 40.0}, "round": 0}
    ts = get_turn_state(match, "b")
    assert ts is not None
    assert ts.is_my_turn is True


def test_ultimatum_accept_sets_outcome_and_finishes():
    """After submit_offer, accept sets payoffs (u = x - v) and status FINISHED."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    get_turn_state(match, "a")
    rv = match.game_state["reservation_values"]
    apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 60, "b": 40}}))
    result = apply_action(match, "b", Action(action_type="accept", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome is not None
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["a"] == round(60.0 - rv["a"], 2)
    assert payoffs["b"] == round(40.0 - rv["b"], 2)


def test_ultimatum_reject_advances_turn():
    """reject advances turn so the other agent can offer."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 60, "b": 40}}))
    result = apply_action(match, "b", Action(action_type="reject", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.RUNNING
    assert match.current_turn_index == 0
    ts = get_turn_state(match, "a")
    assert ts is not None
    assert ts.is_my_turn is True


def test_ultimatum_invalid_offer_rejected():
    """submit_offer with shares not summing to total returns error with invalid_payload."""
    game = UltimatumGame(total=100)
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    match.spec = spec
    result = game.apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 80, "b": 40}}))
    assert result.ok is False
    assert result.error == "invalid_payload"
    assert match.game_state["current_offer"] is None
    assert match.current_turn_index == 0


def test_ultimatum_offer_missing_agent_rejected():
    """submit_offer missing an agent in shares returns error."""
    game = UltimatumGame(total=100)
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    match.spec = spec
    result = game.apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 60}}))
    assert result.ok is False
    assert result.error == "invalid_payload"


def test_ultimatum_accept_without_offer_invalid():
    """accept when there is no current_offer returns error."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    game = get_game("ultimatum")
    assert game is not None
    result = game.apply_action(match, "a", Action(action_type="accept", payload={}))
    assert result.ok is False
    assert result.error == "game_rule_violation"
    assert match.status == MatchStatus.RUNNING


def test_ultimatum_cannot_accept_own_offer():
    """Agent cannot accept their own offer."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 60, "b": 40}}))
    # Manually set turn back to "a" to test the guard
    match.current_turn_index = 0
    game = get_game("ultimatum")
    assert game is not None
    result = game.apply_action(match, "a", Action(action_type="accept", payload={}))
    assert result.ok is False
    assert result.error == "game_rule_violation"
    assert "Cannot accept your own offer" in result.error_detail


def test_ultimatum_not_your_turn_error():
    """Attempting action when it's not your turn returns NOT_YOUR_TURN error."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    result = apply_action(match, "b", Action(action_type="submit_offer", payload={"shares": {"a": 40, "b": 60}}))
    assert result.ok is False
    assert result.error == "not_your_turn"


def test_ultimatum_action_history_tracks_offers():
    """submit_offer appends an entry to action_history with agent_id, action, shares, round."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 70, "b": 30}}))
    apply_action(match, "b", Action(action_type="submit_offer", payload={"shares": {"a": 45, "b": 55}}))
    history = match.game_state["action_history"]
    assert len(history) == 2
    assert history[0] == {"agent_id": "a", "action": "submit_offer", "shares": {"a": 70.0, "b": 30.0}, "round": 0}
    assert history[1] == {"agent_id": "b", "action": "submit_offer", "shares": {"a": 45.0, "b": 55.0}, "round": 0}


def test_ultimatum_action_history_tracks_rejections():
    """reject appends an entry to action_history with agent_id, action, round."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 70, "b": 30}}))
    apply_action(match, "b", Action(action_type="reject", payload={}))
    history = match.game_state["action_history"]
    assert len(history) == 2
    assert history[0]["action"] == "submit_offer"
    assert history[1] == {"agent_id": "b", "action": "reject", "round": 0}


# ---------------------------------------------------------------------------
# 3-player tests
# ---------------------------------------------------------------------------


def test_ultimatum_3player_offer_and_unanimity():
    """3-player: agreement requires all non-proposers to accept."""
    game = UltimatumGame(total=100, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    # a proposes
    result = game.apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 40, "b": 30, "c": 30}}))
    assert result.ok is True
    assert match.game_state["current_offer"] == {"a": 40.0, "b": 30.0, "c": 30.0}
    # b accepts — not enough yet
    result = game.apply_action(match, "b", Action(action_type="accept", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.RUNNING  # c hasn't accepted yet
    assert match.game_state["acceptances"] == {"b": True}
    # c accepts — now unanimity
    result = game.apply_action(match, "c", Action(action_type="accept", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["a"] == round(40.0 - 10, 2)
    assert payoffs["b"] == round(30.0 - 10, 2)
    assert payoffs["c"] == round(30.0 - 10, 2)


def test_ultimatum_3player_reject_clears_acceptances():
    """3-player: a reject clears all pending acceptances."""
    game = UltimatumGame(total=100, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    game.apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 40, "b": 30, "c": 30}}))
    # b accepts
    game.apply_action(match, "b", Action(action_type="accept", payload={}))
    assert match.game_state["acceptances"] == {"b": True}
    # c rejects — clears acceptances
    game.apply_action(match, "c", Action(action_type="reject", payload={}))
    assert match.game_state["acceptances"] == {}
    assert match.status == MatchStatus.RUNNING


def test_ultimatum_3player_new_offer_clears_acceptances():
    """3-player: a new offer clears previous acceptances."""
    game = UltimatumGame(total=100, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    game.apply_action(match, "a", Action(action_type="submit_offer", payload={"shares": {"a": 40, "b": 30, "c": 30}}))
    game.apply_action(match, "b", Action(action_type="accept", payload={}))
    assert match.game_state["acceptances"] == {"b": True}
    # c makes a counter-offer — clears acceptances
    game.apply_action(match, "c", Action(action_type="submit_offer", payload={"shares": {"a": 30, "b": 35, "c": 35}}))
    assert match.game_state["acceptances"] == {}
    assert match.game_state["last_offer_by"] == "c"


# ---------------------------------------------------------------------------
# RANDOM turn order tests
# ---------------------------------------------------------------------------


def test_ultimatum_random_turn_order_any_agent_can_act():
    """In RANDOM mode, any agent can act (no NOT_YOUR_TURN errors)."""
    game = UltimatumGame(total=100, turn_order=TurnOrder.RANDOM, reservation_values={"a": 10, "b": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    match.spec = spec
    # b can act even though turn_index is 0 (would be a's turn in round_robin)
    result = game.apply_action(match, "b", Action(action_type="submit_offer", payload={"shares": {"a": 40, "b": 60}}))
    assert result.ok is True


def test_ultimatum_random_turn_order_is_my_turn_for_all():
    """In RANDOM mode, is_my_turn is True for all agents."""
    game = UltimatumGame(total=100, turn_order=TurnOrder.RANDOM, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    for agent_id in ["a", "b", "c"]:
        ts = game.compute_turn_state(match, agent_id)
        assert ts is not None
        assert ts.is_my_turn is True


def test_ultimatum_random_3player_full_negotiation():
    """3-player RANDOM mode: full negotiation flow ending in agreement."""
    game = UltimatumGame(total=100, turn_order=TurnOrder.RANDOM, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    # c offers (any agent can go first in RANDOM mode)
    result = game.apply_action(match, "c", Action(action_type="submit_offer", payload={"shares": {"a": 33, "b": 33, "c": 34}}))
    assert result.ok is True
    # a accepts
    result = game.apply_action(match, "a", Action(action_type="accept", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.RUNNING  # b hasn't accepted
    # b accepts
    result = game.apply_action(match, "b", Action(action_type="accept", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "agreement"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["a"] == round(33.0 - 10, 2)
    assert payoffs["b"] == round(33.0 - 10, 2)
    assert payoffs["c"] == round(34.0 - 10, 2)


def test_ultimatum_visible_state_includes_agents_and_acceptances():
    """Visible game state includes agents list and current acceptances."""
    game = UltimatumGame(total=100, reservation_values={"a": 10, "b": 10, "c": 10})
    spec = game.spec()
    match = create_match("m1", "ultimatum", spec, ["a", "b", "c"])
    match.spec = spec
    ts = game.compute_turn_state(match, "a")
    assert ts is not None
    assert ts.game_state["agents"] == ["a", "b", "c"]
    assert ts.game_state["acceptances"] == {}
    assert "my_reservation_value" in ts.game_state
