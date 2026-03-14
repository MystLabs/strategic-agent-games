"""MatchLogger: structured event logging for match replay and analysis."""

import copy
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from arena.types import ActionResult, MessageIntent


class MatchEvent(BaseModel):
    """A single event in a match log."""

    timestamp_ns: int = Field(..., description="Monotonic timestamp in nanoseconds")
    event_type: str = Field(..., description="Type of event (e.g. action, message, start, end)")
    agent_id: str | None = Field(default=None, description="Agent that triggered the event")
    data: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")


class MatchLog(BaseModel):
    """Complete log of a match for replay and analysis."""

    match_id: str = Field(..., description="Match id")
    game_id: str = Field(..., description="Game id")
    agent_ids: list[str] = Field(default_factory=list, description="Participating agent ids")
    events: list[MatchEvent] = Field(default_factory=list, description="Ordered event list")
    outcome: dict[str, Any] | None = Field(default=None, description="Match outcome")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")


class MatchLogger:
    """Logs match events and produces a MatchLog for persistence."""

    def __init__(self, match_id: str, game_id: str, agent_ids: list[str]) -> None:
        self._match_id = match_id
        self._game_id = game_id
        self._agent_ids = list(agent_ids)
        self._events: list[MatchEvent] = []
        self._outcome: dict[str, Any] | None = None
        self._metadata: dict[str, Any] = {}

    @staticmethod
    def _strip_action_history(data: dict[str, Any]) -> dict[str, Any]:
        """Remove action_history from turn_state game_state to avoid redundancy."""
        gs = data.get("game_state")
        if isinstance(gs, dict) and "action_history" in gs:
            gs = {k: v for k, v in gs.items() if k != "action_history"}
            data = {**data, "game_state": gs}
        return data

    def log_event(self, event_type: str, agent_id: str | None = None, **data: Any) -> None:
        """Log a generic event."""
        data = copy.deepcopy(data)
        if event_type == "turn_state":
            data = self._strip_action_history(data)
        self._events.append(MatchEvent(
            timestamp_ns=time.time_ns(),
            event_type=event_type,
            agent_id=agent_id,
            data=data,
        ))

    def log_messages(self, agent_id: str, messages: list[MessageIntent]) -> None:
        """Log message intents from an agent."""
        for msg in messages:
            self._events.append(MatchEvent(
                timestamp_ns=time.time_ns(),
                event_type="message",
                agent_id=agent_id,
                data={
                    "scope": msg.scope.value,
                    "content": msg.content,
                    "to_agent_ids": msg.to_agent_ids,
                },
            ))

    def log_action(self, agent_id: str, action_type: str, payload: dict[str, Any], result: ActionResult) -> None:
        """Log an action attempt and its result."""
        d: dict[str, Any] = {"action_type": action_type, "payload": payload, "ok": result.ok}
        if not result.ok:
            d["error"] = result.error
            d["error_detail"] = result.error_detail
        self._events.append(MatchEvent(
            timestamp_ns=time.time_ns(),
            event_type="action",
            agent_id=agent_id,
            data=d,
        ))

    def set_outcome(self, outcome: dict[str, Any] | None) -> None:
        """Set the match outcome."""
        self._outcome = outcome

    def set_metadata(self, **kwargs: Any) -> None:
        """Set arbitrary metadata."""
        self._metadata.update(kwargs)

    def to_log(self) -> MatchLog:
        """Build the MatchLog."""
        return MatchLog(
            match_id=self._match_id,
            game_id=self._game_id,
            agent_ids=self._agent_ids,
            events=list(self._events),
            outcome=self._outcome,
            metadata=dict(self._metadata),
        )

    def save(self, directory: Path) -> Path:
        """Write the match log as JSON to directory/{match_id}.json."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._match_id}.json"
        log = self.to_log()
        path.write_text(log.model_dump_json())
        return path

    @staticmethod
    def load(path: Path) -> MatchLog:
        """Load a MatchLog from a JSON file."""
        data = json.loads(path.read_text())
        return MatchLog.model_validate(data)
