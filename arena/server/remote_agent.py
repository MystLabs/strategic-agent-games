"""RemoteAgent: Agent adapter that forwards act() calls to an HTTP endpoint."""

from __future__ import annotations

import httpx
from typing import Any

from arena.agents.base import Agent
from arena.types import AgentResponse, TurnState


class RemoteAgent(Agent):
    """Agent that POSTs TurnState to a remote HTTP endpoint and parses AgentResponse."""

    def __init__(self, agent_id: str, endpoint: str, timeout: float = 30.0) -> None:
        self._agent_id = agent_id
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def act(self, state: TurnState) -> AgentResponse:
        url = f"{self._endpoint}/act"
        resp = self._client.post(url, json=state.model_dump(mode="json"))
        resp.raise_for_status()
        return AgentResponse.model_validate(resp.json())

    def on_match_start(self, match_id: str, game_id: str, agent_ids: list[str]) -> None:
        try:
            self._client.post(
                f"{self._endpoint}/match_start",
                json={"match_id": match_id, "game_id": game_id, "agent_ids": agent_ids},
            )
        except Exception:
            pass  # Non-critical lifecycle hook

    def on_match_end(self, match_id: str, outcome: dict[str, Any] | None) -> None:
        try:
            self._client.post(
                f"{self._endpoint}/match_end",
                json={"match_id": match_id, "outcome": outcome},
            )
        except Exception:
            pass

    def get_metadata(self) -> dict[str, Any]:
        meta = super().get_metadata()
        meta["endpoint"] = self._endpoint
        meta["type"] = "remote"
        return meta
