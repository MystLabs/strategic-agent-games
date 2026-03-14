"""Match state: one running instance of a game."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from arena.spec import GameSpec
from arena.types import Message


class MatchStatus(str, Enum):
    """Status of a match."""

    WAITING = "waiting"  # waiting for enough agents to join
    RUNNING = "running"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class Match(BaseModel):
    """State of a single match (one game instance)."""

    match_id: str = Field(..., description="Unique match id")
    game_id: str = Field(..., description="Game being played")
    spec: GameSpec = Field(..., description="Game spec (redundant with game_id but convenient)")
    agent_ids: list[str] = Field(default_factory=list, description="Agent ids in turn order (when round-robin)")
    status: MatchStatus = Field(default=MatchStatus.WAITING, description="Current match status")
    current_phase_index: int = Field(default=0, description="Index into spec.phases")
    current_round: int = Field(default=0, description="Round within current phase (if applicable)")
    current_turn_index: int = Field(default=0, description="Index into agent_ids for whose turn (if round-robin)")
    game_state: dict[str, Any] = Field(default_factory=dict, description="Game-specific state")
    messages: list[Message] = Field(default_factory=list, description="All messages in this match")
    outcome: dict[str, Any] | None = Field(default=None, description="Set when status=finished (payoffs, etc.)")
