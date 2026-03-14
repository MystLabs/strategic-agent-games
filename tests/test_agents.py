"""Tests for Agent base class and RandomAgent."""

import pytest

from arena.agents.base import Agent
from arena.agents.random_agent import RandomAgent
from arena.types import Action, AgentResponse, AllowedAction, TurnState


_DEFAULT_ALLOWED = [
    AllowedAction(action_type="submit_offer", description="Propose a split", payload_schema={"my_share": {"type": "number"}}),
    AllowedAction(action_type="accept", description="Accept current offer", payload_schema={}),
    AllowedAction(action_type="reject", description="Reject current offer", payload_schema={}),
]


def _make_turn_state(allowed_actions: list[AllowedAction] | None = None) -> TurnState:
    """Helper to build a minimal TurnState for testing."""
    actions = _DEFAULT_ALLOWED if allowed_actions is None else allowed_actions
    return TurnState(
        match_id="m1",
        game_id="ultimatum",
        agent_id="test_agent",
        phase="negotiation",
        is_my_turn=True,
        current_turn_agent_id="test_agent",
        game_state={"total": 100, "current_offer": None, "last_offer_by": None, "agents": ["test_agent", "opponent"]},
        messages=[],
        allowed_actions=actions,
    )


def test_agent_base_class_is_abstract():
    """Agent cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Agent()


def test_random_agent_has_agent_id():
    """RandomAgent has a valid agent_id."""
    agent = RandomAgent(agent_id="alice")
    assert agent.agent_id == "alice"


def test_random_agent_default_agent_id():
    """RandomAgent generates a default agent_id if none given."""
    agent = RandomAgent()
    assert agent.agent_id.startswith("random_")


def test_random_agent_act_returns_agent_response():
    """act() returns an AgentResponse."""
    agent = RandomAgent(seed=42)
    state = _make_turn_state()
    response = agent.act(state)
    assert isinstance(response, AgentResponse)
    assert isinstance(response.action, Action)


def test_random_agent_act_picks_from_allowed_actions():
    """act() picks an action_type from the allowed actions list."""
    agent = RandomAgent(seed=42)
    state = _make_turn_state()
    allowed_types = {a.action_type for a in state.allowed_actions}
    for _ in range(20):
        response = agent.act(state)
        assert response.action.action_type in allowed_types


def test_random_agent_seeded_reproducibility():
    """Two agents with the same seed produce identical sequences."""
    state = _make_turn_state()
    a1 = RandomAgent(seed=123)
    a2 = RandomAgent(seed=123)
    for _ in range(10):
        r1 = a1.act(state)
        r2 = a2.act(state)
        assert r1.action.action_type == r2.action.action_type
        assert r1.action.payload == r2.action.payload


def test_random_agent_submit_offer_payload_valid():
    """submit_offer payloads have shares dict summing to total."""
    agent = RandomAgent(seed=42)
    state = _make_turn_state(allowed_actions=[
        AllowedAction(action_type="submit_offer", description="Propose", payload_schema={}),
    ])
    for _ in range(50):
        response = agent.act(state)
        assert response.action.action_type == "submit_offer"
        shares = response.action.payload["shares"]
        assert set(shares.keys()) == {"test_agent", "opponent"}
        assert all(v >= 0 for v in shares.values())
        assert abs(sum(shares.values()) - 100) < 0.02


def test_random_agent_empty_allowed_actions():
    """When no actions are allowed, agent returns noop."""
    agent = RandomAgent(seed=42)
    state = _make_turn_state(allowed_actions=[])
    response = agent.act(state)
    assert response.action.action_type == "noop"
