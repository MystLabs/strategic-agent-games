"""RandomAgent: picks a random allowed action with valid random payload."""

import random
import threading
import uuid

from arena.agents.base import Agent
from arena.types import Action, AgentResponse, TurnState


class RandomAgent(Agent):
    """Agent that picks a random allowed action with a valid random payload."""

    def __init__(self, agent_id: str | None = None, seed: int | None = None) -> None:
        self._agent_id = agent_id or f"random_{uuid.uuid4().hex[:8]}"
        self._rng = random.Random(seed)
        self._rng_lock = threading.Lock()

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def act(self, state: TurnState) -> AgentResponse:
        if not state.allowed_actions:
            return AgentResponse(action=Action(action_type="noop", payload={}))
        with self._rng_lock:
            chosen = self._rng.choice(state.allowed_actions)
            payload = self._random_payload(chosen.action_type, state)
        return AgentResponse(action=Action(action_type=chosen.action_type, payload=payload))

    def _random_payload(self, action_type: str, state: TurnState) -> dict:
        """Generate a valid random payload for known action types.

        Must be called while holding self._rng_lock.
        """
        if action_type == "submit_offer":
            agents = state.game_state.get("agents", [])
            total = state.game_state.get("total", 100)
            if agents:
                # Generate random shares that sum to total
                raw = [self._rng.random() for _ in agents]
                s = sum(raw)
                shares = {aid: round(total * r / s, 2) for aid, r in zip(agents, raw)}
                # Fix rounding so shares sum exactly to total
                diff = round(total - sum(shares.values()), 2)
                first = agents[0]
                shares[first] = round(shares[first] + diff, 2)
                return {"shares": shares}
            return {"shares": {}}
        if action_type in ("accept", "reject", "pass", "message_only", "noop"):
            return {}
        return {}
