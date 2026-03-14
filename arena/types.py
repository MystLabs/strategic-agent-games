"""Shared types for the negotiation environment."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageScope(str, Enum):
    """Who can see the message."""

    PUBLIC = "public"
    PRIVATE = "private"


class Message(BaseModel):
    """A message sent by an agent (public or private)."""

    message_id: str = Field(..., description="Unique id for this message")
    sender_id: str = Field(..., description="Agent who sent the message")
    scope: MessageScope = Field(..., description="Public or private")
    content: str = Field(..., description="Message text")
    to_agent_ids: list[str] = Field(default_factory=list, description="For private: recipient agent ids")
    timestamp_ns: int | None = Field(default=None, description="Optional monotonic timestamp")


class Action(BaseModel):
    """A single action (message or game action) performed by an agent."""

    action_type: str = Field(..., description="e.g. send_public_message, submit_offer, place_bid, accept")
    payload: dict[str, Any] = Field(default_factory=dict, description="Action-specific parameters")


class AllowedAction(BaseModel):
    """Describes an action the agent is allowed to take this turn."""

    action_type: str = Field(..., description="Type of action")
    description: str = Field(default="", description="Human-readable description")
    payload_schema: dict[str, Any] = Field(default_factory=dict, description="JSON schema for payload (optional)")


class TurnState(BaseModel):
    """What get_turn_state returns: everything the agent needs to decide and act."""

    match_id: str = Field(..., description="Current match id")
    game_id: str = Field(..., description="Game being played")
    agent_id: str = Field(..., description="Id of the agent receiving this state")
    phase: str = Field(..., description="Current phase name")
    is_my_turn: bool = Field(..., description="Whether this agent may act now")
    current_turn_agent_id: str | None = Field(default=None, description="Whose turn it is (if turn-based)")
    game_state: dict[str, Any] = Field(default_factory=dict, description="Visible game state (spec-defined)")
    messages: list[Message] = Field(default_factory=list, description="Recent messages this agent can see")
    allowed_actions: list[AllowedAction] = Field(default_factory=list, description="Actions allowed this turn")
    game_over: bool = Field(default=False, description="True if match has ended")
    outcome: dict[str, Any] | None = Field(default=None, description="If game_over: outcome and payoffs (spec-defined)")


class Payoff(BaseModel):
    """Payoff for one agent after the game ends."""

    agent_id: str = Field(..., description="Agent id")
    value: float = Field(..., description="Payoff value (e.g. dollars, utility)")


class ActionError(str, Enum):
    """Structured error codes for action results."""

    MATCH_NOT_FOUND = "match_not_found"
    MATCH_NOT_RUNNING = "match_not_running"
    NOT_YOUR_TURN = "not_your_turn"
    INVALID_ACTION_TYPE = "invalid_action_type"
    INVALID_PAYLOAD = "invalid_payload"
    GAME_RULE_VIOLATION = "game_rule_violation"
    AGENT_NOT_IN_MATCH = "agent_not_in_match"


class ActionResult(BaseModel):
    """Structured result returned by action/message operations."""

    ok: bool = Field(..., description="Whether the operation succeeded")
    error: str | None = Field(default=None, description="Error code if failed")
    error_detail: str | None = Field(default=None, description="Human-readable error detail")


def action_ok() -> ActionResult:
    """Create a successful ActionResult."""
    return ActionResult(ok=True)


def action_error(error: ActionError | str, detail: str | None = None) -> ActionResult:
    """Create a failed ActionResult with error code and optional detail."""
    code = error.value if isinstance(error, ActionError) else error
    return ActionResult(ok=False, error=code, error_detail=detail)


class MessageIntent(BaseModel):
    """Lightweight message intent from an agent (runner fills sender_id, message_id, etc.)."""

    scope: MessageScope = Field(..., description="Public or private")
    content: str = Field(..., description="Message text")
    to_agent_ids: list[str] = Field(default_factory=list, description="For private: recipient agent ids")


class AgentResponse(BaseModel):
    """What an agent returns from act(): messages to send + a game action."""

    messages: list[MessageIntent] = Field(default_factory=list, description="Messages to send before acting")
    action: Action = Field(..., description="The game action to perform")
