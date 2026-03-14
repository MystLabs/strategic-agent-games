"""Session manager: create/join game sessions for the polling API."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from arena.server.polling_agent import PollingAgent


class SessionStatus(str, Enum):
    WAITING = "waiting"      # waiting for players to join
    RUNNING = "running"      # match in progress
    FINISHED = "finished"    # match done
    ERROR = "error"


@dataclass
class SessionPlayer:
    player_id: str
    token: str
    display_name: str = ""
    invite_code: str = ""


@dataclass
class ChatMessage:
    sender_id: str
    content: str
    timestamp: float = field(default_factory=time.time)
    scope: str = "public"
    to_player_ids: list[str] = field(default_factory=list)


@dataclass
class GameSession:
    session_id: str
    game_id: str
    status: SessionStatus = SessionStatus.WAITING
    players: list[SessionPlayer] = field(default_factory=list)
    invite_codes: list[str] = field(default_factory=list)
    polling_agents: dict[str, PollingAgent] = field(default_factory=dict)
    chat_messages: list[ChatMessage] = field(default_factory=list)
    game_events: list[dict[str, Any]] = field(default_factory=list)
    game_params: dict[str, Any] = field(default_factory=dict)
    max_turns: int = 20
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    match_thread: threading.Thread | None = field(default=None, repr=False)


def _generate_token() -> str:
    return f"pt_{secrets.token_urlsafe(24)}"


def _generate_invite() -> str:
    return f"inv_{secrets.token_urlsafe(16)}"


class SessionManager:
    """Manages game sessions for the polling API."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, GameSession] = {}
        self._invite_to_session: dict[str, str] = {}  # invite_code -> session_id
        self._token_to_session: dict[str, tuple[str, str]] = {}  # token -> (session_id, player_id)

    def create_session(
        self,
        game_id: str,
        num_players: int = 2,
        creator_name: str = "",
        game_params: dict[str, Any] | None = None,
        max_turns: int = 20,
    ) -> dict[str, Any]:
        """Create a new session. Returns session info with invite codes."""
        session_id = f"sess_{secrets.token_urlsafe(8)}"
        player_id = f"player_{secrets.token_urlsafe(6)}"
        token = _generate_token()

        # Generate invite codes for remaining slots
        invite_codes = [_generate_invite() for _ in range(num_players - 1)]

        creator = SessionPlayer(
            player_id=player_id,
            token=token,
            display_name=creator_name or player_id,
        )

        # Use display name as agent_id so match history/leaderboard show meaningful names
        agent_name = creator.display_name or player_id
        polling_agent = PollingAgent(agent_name, display_name=creator.display_name)

        session = GameSession(
            session_id=session_id,
            game_id=game_id,
            players=[creator],
            invite_codes=list(invite_codes),
            polling_agents={player_id: polling_agent},
            game_params=game_params or {},
            max_turns=max_turns,
        )

        with self._lock:
            self._sessions[session_id] = session
            for inv in invite_codes:
                self._invite_to_session[inv] = session_id
            self._token_to_session[token] = (session_id, player_id)

        return {
            "session_id": session_id,
            "player_id": player_id,
            "token": token,
            "game_id": game_id,
            "invite_codes": invite_codes,
            "status": session.status.value,
        }

    def join_session(
        self,
        invite_code: str,
        player_name: str = "",
    ) -> dict[str, Any] | None:
        """Join a session via invite code. Returns player info or None if invalid."""
        with self._lock:
            session_id = self._invite_to_session.get(invite_code)
            if session_id is None:
                return None
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.status != SessionStatus.WAITING:
                return None

            # Consume the invite code
            if invite_code not in session.invite_codes:
                return None
            session.invite_codes.remove(invite_code)
            del self._invite_to_session[invite_code]

            player_id = f"player_{secrets.token_urlsafe(6)}"
            token = _generate_token()

            player = SessionPlayer(
                player_id=player_id,
                token=token,
                display_name=player_name or player_id,
                invite_code=invite_code,
            )
            session.players.append(player)

            # Use display name as agent_id so match history/leaderboard show meaningful names
            agent_name = player.display_name or player_id
            polling_agent = PollingAgent(agent_name, display_name=player.display_name)
            session.polling_agents[player_id] = polling_agent

            self._token_to_session[token] = (session_id, player_id)

        return {
            "session_id": session_id,
            "player_id": player_id,
            "token": token,
            "game_id": session.game_id,
            "status": session.status.value,
            "players_joined": len(session.players),
        }

    def authenticate(self, token: str) -> tuple[GameSession, str] | None:
        """Look up session and player_id from a token. Returns (session, player_id) or None."""
        with self._lock:
            entry = self._token_to_session.get(token)
            if entry is None:
                return None
            session_id, player_id = entry
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session, player_id

    def get_session(self, session_id: str) -> GameSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def is_ready_to_start(self, session_id: str) -> bool:
        """True if all invite codes have been consumed (all players joined)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            return session.status == SessionStatus.WAITING and len(session.invite_codes) == 0

    def set_status(self, session_id: str, status: SessionStatus, error: str | None = None) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.status = status
                if error:
                    session.error = error

    def add_chat_message(
        self,
        session_id: str,
        sender_id: str,
        content: str,
        scope: str = "public",
        to_player_ids: list[str] | None = None,
    ) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            msg = ChatMessage(
                sender_id=sender_id,
                content=content,
                scope=scope,
                to_player_ids=to_player_ids or [],
            )
            session.chat_messages.append(msg)
            return True

    def get_chat_messages(
        self,
        session_id: str,
        player_id: str,
        since_index: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            messages = []
            for i, msg in enumerate(session.chat_messages):
                if i < since_index:
                    continue
                # Filter: public messages or private messages addressed to this player
                if msg.scope == "private" and player_id not in msg.to_player_ids and msg.sender_id != player_id:
                    continue
                messages.append({
                    "index": i,
                    "sender_id": msg.sender_id,
                    "content": msg.content,
                    "scope": msg.scope,
                    "to_player_ids": msg.to_player_ids,
                    "timestamp": msg.timestamp,
                })
            return messages

    def add_game_event(self, session_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.game_events.append(event)

    def get_game_events(
        self,
        session_id: str,
        since_index: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            return [
                {"index": i, **ev}
                for i, ev in enumerate(session.game_events)
                if i >= since_index
            ]

    def expire_stale_sessions(self, max_waiting_seconds: float = 300) -> int:
        """Close waiting sessions that have been idle too long. Returns count expired."""
        now = time.time()
        expired = 0
        with self._lock:
            for s in list(self._sessions.values()):
                if s.status == SessionStatus.WAITING and (now - s.created_at) > max_waiting_seconds:
                    s.status = SessionStatus.FINISHED
                    s.error = "Session expired: no opponent joined"
                    # Clean up invite codes
                    for inv in s.invite_codes:
                        self._invite_to_session.pop(inv, None)
                    s.invite_codes.clear()
                    expired += 1
        return expired

    def list_sessions(self, status: str | None = None, game_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for s in self._sessions.values():
                if status and s.status.value != status:
                    continue
                if game_id and s.game_id != game_id:
                    continue
                entry: dict[str, Any] = {
                    "session_id": s.session_id,
                    "game_id": s.game_id,
                    "status": s.status.value,
                    "num_players": len(s.players),
                    "slots_remaining": len(s.invite_codes),
                    "created_at": s.created_at,
                    "players": [
                        {"player_id": p.player_id, "display_name": p.display_name}
                        for p in s.players
                    ],
                }
                # Expose invite codes for waiting sessions so agents can join
                if s.status == SessionStatus.WAITING and s.invite_codes:
                    entry["invite_codes"] = list(s.invite_codes)
                # Include event count for running/finished sessions
                if s.status in (SessionStatus.RUNNING, SessionStatus.FINISHED):
                    entry["events_total"] = len(s.game_events)
                result.append(entry)
            return result
