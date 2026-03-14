"""Tests for core: create_match, get_turn_state, apply_message."""

from arena.core.match import MatchStatus
from arena.core.runner import apply_message, create_match, get_turn_state
from arena.games import get_game_spec
from arena.spec import GameSpec, OutcomeRule, Phase, TurnOrder
from arena.types import MessageScope


def test_create_match_builds_match_with_spec_state():
    """create_match copies initial_game_state and sets status RUNNING."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["agent_a", "agent_b"])
    assert match.match_id == "m1"
    assert match.game_id == "ultimatum"
    assert match.status == MatchStatus.RUNNING
    assert match.agent_ids == ["agent_a", "agent_b"]
    assert match.game_state == {"total": 100, "current_offer": None, "last_offer_by": None, "acceptances": {}, "reservation_values": None, "action_history": []}
    assert match.messages == []
    assert match.outcome is None
    assert match.current_phase_index == 0
    assert match.current_turn_index == 0


def test_create_match_does_not_mutate_spec_initial_state():
    """create_match uses a copy of initial_game_state."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    original = spec.initial_game_state
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    assert match.game_state is not original
    match.game_state["total"] = 999
    assert spec.initial_game_state.get("total") == 100


def test_get_turn_state_returns_turn_state_for_agent():
    """get_turn_state returns TurnState with phase, is_my_turn, game_state."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["agent_a", "agent_b"])
    ts = get_turn_state(match, "agent_a")
    assert ts is not None
    assert ts.match_id == "m1"
    assert ts.game_id == "ultimatum"
    assert ts.agent_id == "agent_a"
    assert ts.phase == "negotiation"
    assert ts.is_my_turn is True
    assert ts.current_turn_agent_id == "agent_a"
    assert ts.game_state.get("total") == 100
    assert ts.game_state.get("current_offer") is None
    assert ts.game_state.get("last_offer_by") is None
    assert "my_reservation_value" in ts.game_state
    assert "reservation_values" not in ts.game_state
    assert ts.messages == []
    assert len(ts.allowed_actions) == 5  # submit_offer, accept, reject, pass, message_only
    assert ts.game_over is False
    assert ts.outcome is None


def test_get_turn_state_round_robin_second_agent_not_turn():
    """Second agent sees is_my_turn=False when current_turn_index is 0."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["agent_a", "agent_b"])
    ts_b = get_turn_state(match, "agent_b")
    assert ts_b is not None
    assert ts_b.agent_id == "agent_b"
    assert ts_b.is_my_turn is False
    assert ts_b.current_turn_agent_id == "agent_a"


def test_get_turn_state_unknown_game_returns_none():
    """get_turn_state for unregistered game_id returns None."""
    spec = GameSpec(
        game_id="unknown_game",
        name="Unknown",
        phases=[Phase(name="phase1", turn_order=TurnOrder.ROUND_ROBIN, allowed_action_types=[])],
        outcome_rule=OutcomeRule.ENGINE,
        initial_game_state={"x": 1},
    )
    match = create_match("m1", "unknown_game", spec, ["only_agent"])
    ts = get_turn_state(match, "only_agent")
    assert ts is None


def test_apply_message_appends_public_message():
    """apply_message appends a message with message_id and timestamp."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    result = apply_message(match, "a", "public", "Hello all", None)
    assert result.ok is True
    assert len(match.messages) == 1
    msg = match.messages[0]
    assert msg.sender_id == "a"
    assert msg.scope == MessageScope.PUBLIC
    assert msg.content == "Hello all"
    assert msg.to_agent_ids == []
    assert msg.message_id != ""
    assert msg.timestamp_ns is not None


def test_apply_message_appends_private_message():
    """apply_message with private scope sets to_agent_ids."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    result = apply_message(match, "a", "private", "Secret", ["b"])
    assert result.ok is True
    assert len(match.messages) == 1
    assert match.messages[0].scope == MessageScope.PRIVATE
    assert match.messages[0].to_agent_ids == ["b"]


def test_apply_message_does_not_advance_turn():
    """Messages do NOT advance current_turn_index (turns only advance on game actions)."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    assert match.current_turn_index == 0
    result = apply_message(match, "a", "public", "msg", None)
    assert result.ok is True
    assert match.current_turn_index == 0
    result2 = apply_message(match, "b", "public", "msg2", None)
    assert result2.ok is True
    assert match.current_turn_index == 0
    assert match.current_round == 0


def test_get_turn_state_includes_messages_after_apply_message():
    """get_turn_state returns the messages appended by apply_message."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    apply_message(match, "a", "public", "Hello", None)
    ts = get_turn_state(match, "b")
    assert ts is not None
    assert len(ts.messages) == 1
    assert ts.messages[0].content == "Hello"


def test_apply_message_rejected_when_finished():
    """apply_message returns error when match is finished; message is NOT appended."""
    spec = get_game_spec("ultimatum")
    assert spec is not None
    match = create_match("m1", "ultimatum", spec, ["a", "b"])
    match.status = MatchStatus.FINISHED
    result = apply_message(match, "a", "public", "late", None)
    assert result.ok is False
    assert result.error == "match_not_running"
    assert len(match.messages) == 0
    assert match.current_turn_index == 0
