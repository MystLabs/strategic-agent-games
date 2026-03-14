"""PollingAgent: bridges the polling API with the ExperimentRunner.

When the runner calls agent.act(), this agent blocks until the real player
submits an action via the HTTP polling API.
"""

from __future__ import annotations

import threading
from typing import Any

from arena.agents.base import Agent
from arena.types import (
    Action,
    AgentResponse,
    MessageIntent,
    MessageScope,
    TurnState,
)


class IdleTimeoutError(Exception):
    """Raised when a polling agent has been idle for too many consecutive turns."""


class PollingAgent(Agent):
    """Agent that blocks on act() until a human/AI submits via the polling API."""

    # How long to wait for a player action before auto-passing (seconds)
    IDLE_TIMEOUT = 60
    # After this many consecutive idle timeouts, raise to end the match
    MAX_CONSECUTIVE_IDLE = 3

    def __init__(self, player_id: str, display_name: str = "") -> None:
        self._player_id = player_id
        self._display_name = display_name or player_id

        # Synchronisation between the runner thread and the API thread
        self._state_ready = threading.Event()
        self._action_ready = threading.Event()
        self._lock = threading.Lock()
        self._idle_passes = 0  # consecutive idle timeouts

        self._current_state: TurnState | None = None
        self._pending_response: AgentResponse | None = None
        self._match_started = threading.Event()
        self._match_info: dict[str, Any] = {}
        self._match_outcome: dict[str, Any] | None = None
        self._match_ended = threading.Event()

    @property
    def agent_id(self) -> str:
        return self._player_id

    def get_metadata(self) -> dict[str, Any]:
        meta = super().get_metadata()
        meta["display_name"] = self._display_name
        return meta

    # --- Called by ExperimentRunner (in runner thread) ---

    def on_match_start(self, match_id: str, game_id: str, agent_ids: list[str]) -> None:
        with self._lock:
            self._match_info = {
                "match_id": match_id,
                "game_id": game_id,
                "agent_ids": agent_ids,
            }
        self._match_started.set()

    def on_match_end(self, match_id: str, outcome: dict[str, Any] | None) -> None:
        with self._lock:
            self._match_outcome = outcome
        self._match_ended.set()
        # Unblock act() if it's waiting — the runner is done
        self._action_ready.set()

    def act(self, state: TurnState) -> AgentResponse:
        """Block until the player submits an action via the polling API."""
        # Publish state for the polling endpoint
        with self._lock:
            self._current_state = state
            self._pending_response = None
        self._action_ready.clear()
        self._state_ready.set()

        # Wait for the player to submit, with idle timeout
        got_action = self._action_ready.wait(timeout=self.IDLE_TIMEOUT)

        with self._lock:
            resp = self._pending_response
            self._current_state = None
            self._state_ready.clear()

        if resp is None or not got_action:
            # Timed out or match ended — return a pass
            self._idle_passes += 1
            if self._idle_passes >= self.MAX_CONSECUTIVE_IDLE:
                raise IdleTimeoutError(
                    f"Agent {self._player_id} idle for {self._idle_passes} consecutive turns"
                )
            return AgentResponse(
                messages=[],
                action=Action(action_type="pass", payload={}),
            )
        self._idle_passes = 0
        return resp

    @property
    def consecutive_idle_passes(self) -> int:
        return self._idle_passes

    # --- Called by the polling API (in request thread) ---

    def get_current_state(self, timeout: float = 30.0) -> TurnState | None:
        """Wait for state to become available, then return it."""
        self._state_ready.wait(timeout=timeout)
        with self._lock:
            return self._current_state

    def peek_state(self) -> TurnState | None:
        """Return current state without blocking."""
        with self._lock:
            return self._current_state

    def submit_action(
        self,
        action_type: str,
        payload: dict[str, Any] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Submit an action from the polling API. Returns True if accepted."""
        with self._lock:
            if self._current_state is None:
                return False

            msg_intents = []
            for m in (messages or []):
                scope = MessageScope.PRIVATE if m.get("scope") == "private" else MessageScope.PUBLIC
                msg_intents.append(MessageIntent(
                    scope=scope,
                    content=m.get("content", ""),
                    to_agent_ids=m.get("to_agent_ids", []),
                ))

            self._pending_response = AgentResponse(
                messages=msg_intents,
                action=Action(
                    action_type=action_type,
                    payload=payload or {},
                ),
            )

        self._action_ready.set()
        return True

    def is_waiting_for_action(self) -> bool:
        """True if the runner is blocked waiting for this player's action."""
        with self._lock:
            return self._current_state is not None and self._pending_response is None

    def get_match_info(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._match_info)

    def get_match_outcome(self) -> dict[str, Any] | None:
        with self._lock:
            return self._match_outcome

    def has_match_ended(self) -> bool:
        return self._match_ended.is_set()
