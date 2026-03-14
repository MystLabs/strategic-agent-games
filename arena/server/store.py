"""In-memory store for arena: registered agents, match history, per-game ELO ratings."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegisteredAgent:
    agent_id: str
    endpoint: str | None  # None = built-in agent
    agent_type: str  # "remote", "random", "langchain"
    display_name: str = ""
    supported_games: list[str] = field(default_factory=list)  # empty = all games
    registered_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchRecord:
    match_id: str
    game_id: str
    agent_ids: list[str]
    outcome: dict[str, Any] | None = None
    status: str = ""
    num_turns: int = 0
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)
    log: dict[str, Any] | None = None
    game_params: dict[str, Any] | None = None


class ArenaStore:
    """Thread-safe in-memory store for arena state with per-game leaderboard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agents: dict[str, RegisteredAgent] = {}
        self._matches: list[MatchRecord] = []
        # Per-game stats: [game_id][agent_id] -> counters
        self._games_played: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._deals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._auction_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._total_utility: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._utility_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Name claiming: name -> claim_token (first use claims the name)
        self._claimed_names: dict[str, str] = {}

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    def claim_name(self, name: str, claim_token: str | None = None) -> tuple[bool, str]:
        """Claim a display name. Returns (ok, token).

        - First use: name is claimed, a new token is returned.
        - Subsequent use with correct token: ok.
        - Subsequent use with wrong/no token: rejected.
        """
        with self._lock:
            existing = self._claimed_names.get(name)
            if existing is None:
                # First claim
                import secrets as _sec
                token = claim_token or f"ct_{_sec.token_urlsafe(16)}"
                self._claimed_names[name] = token
                return True, token
            if claim_token and claim_token == existing:
                return True, existing
            return False, ""

    def verify_name(self, name: str, claim_token: str | None) -> bool:
        """Check if a name can be used with the given claim token."""
        with self._lock:
            existing = self._claimed_names.get(name)
            if existing is None:
                return True  # unclaimed, anyone can use it
            return claim_token is not None and claim_token == existing

    def register_agent(self, agent_id: str, endpoint: str | None, agent_type: str,
                       display_name: str = "", supported_games: list[str] | None = None,
                       metadata: dict[str, Any] | None = None) -> RegisteredAgent:
        with self._lock:
            agent = RegisteredAgent(
                agent_id=agent_id,
                endpoint=endpoint,
                agent_type=agent_type,
                display_name=display_name or agent_id,
                supported_games=supported_games or [],
                metadata=metadata or {},
            )
            self._agents[agent_id] = agent
            return agent

    def get_agent(self, agent_id: str) -> RegisteredAgent | None:
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self) -> list[RegisteredAgent]:
        with self._lock:
            return list(self._agents.values())

    def remove_agent(self, agent_id: str) -> bool:
        with self._lock:
            return self._agents.pop(agent_id, None) is not None

    def record_match(self, match_id: str, game_id: str, agent_ids: list[str],
                     outcome: dict[str, Any] | None, status: str, num_turns: int,
                     duration_seconds: float, log: dict[str, Any] | None = None,
                     game_params: dict[str, Any] | None = None) -> None:
        record = MatchRecord(
            match_id=match_id, game_id=game_id, agent_ids=agent_ids,
            outcome=outcome, status=status, num_turns=num_turns,
            duration_seconds=duration_seconds, log=log, game_params=game_params,
        )
        with self._lock:
            self._matches.append(record)
            self._update_stats(game_id, agent_ids, outcome)

    def _update_stats(self, game_id: str, agent_ids: list[str], outcome: dict[str, Any] | None) -> None:
        """Update per-game stats. Must be called with lock held."""
        for aid in agent_ids:
            self._games_played[game_id][aid] += 1

        if not outcome:
            return

        payoffs = outcome.get("payoffs", [])
        if not payoffs:
            return

        reason = outcome.get("trigger") or outcome.get("reason") or ""
        is_auction = game_id == "first-price-auction"

        payoff_map: dict[str, float] = {}
        for p in payoffs:
            aid = p.get("agent_id", "")
            u = float(p.get("utility", p.get("value", 0)))
            payoff_map[aid] = u
            self._total_utility[game_id][aid] += u
            self._utility_count[game_id][aid] += 1

        has_positive_utility = any(payoff_map.get(a, 0) > 0 for a in agent_ids)
        is_deal = "accept" in reason or reason in ("deal", "agreement") or has_positive_utility

        if is_auction:
            # Winner = agent with positive utility (paid less than valuation)
            for aid in agent_ids:
                if payoff_map.get(aid, 0) > 0:
                    self._auction_wins[game_id][aid] += 1
        else:
            # Deal = both got positive utility (or accepted)
            if is_deal:
                for aid in agent_ids:
                    self._deals[game_id][aid] += 1

    def get_leaderboard(self, game_id: str | None = None) -> list[dict[str, Any]]:
        """Get per-game leaderboard."""
        with self._lock:
            if not game_id:
                return []
            return self._leaderboard_for_game(game_id)

    def _leaderboard_for_game(self, game_id: str) -> list[dict[str, Any]]:
        is_auction = game_id == "first-price-auction"
        board = []
        for aid, played in self._games_played[game_id].items():
            if played == 0:
                continue
            total_u = self._total_utility[game_id].get(aid, 0.0)
            u_count = self._utility_count[game_id].get(aid, 0)
            avg_u = total_u / u_count if u_count > 0 else 0.0
            # Use registered agent info if available, otherwise just the id
            agent = self._agents.get(aid)
            entry: dict[str, Any] = {
                "agent_id": aid,
                "display_name": agent.display_name if agent else aid,
                "agent_type": agent.agent_type if agent else "player",
                "matches": played,
                "avg_utility": round(avg_u, 1),
            }
            if is_auction:
                entry["auction_wins"] = self._auction_wins[game_id].get(aid, 0)
            else:
                entry["deals"] = self._deals[game_id].get(aid, 0)
            board.append(entry)
        board.sort(key=lambda x: x["avg_utility"], reverse=True)
        return board

    def get_match_history(self, limit: int = 50, game_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            matches = self._matches
            if game_id:
                matches = [m for m in matches if m.game_id == game_id]
            recent = matches[-limit:][::-1]
            return [
                {
                    "match_id": m.match_id,
                    "game_id": m.game_id,
                    "agent_ids": m.agent_ids,
                    "outcome": m.outcome,
                    "status": m.status,
                    "num_turns": m.num_turns,
                    "duration_seconds": round(m.duration_seconds, 2),
                    "timestamp": m.timestamp,
                    "log": m.log,
                    "game_params": m.game_params,
                }
                for m in recent
            ]
