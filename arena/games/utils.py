"""Shared helpers for game implementations."""

from arena.spec import GameSpec
from arena.types import AllowedAction, MessageScope


def messages_visible_to(messages: list, agent_id: str) -> list:
    """Return messages this agent can see (public + private to/from them)."""
    out = []
    for m in messages:
        if m.scope == MessageScope.PUBLIC:
            out.append(m)
        elif agent_id == m.sender_id or agent_id in m.to_agent_ids:
            out.append(m)
    return out


def build_allowed_actions(spec: GameSpec, phase_name: str, is_my_turn: bool) -> list[AllowedAction]:
    """Build allowed_actions from spec for current phase; only game actions (no message types)."""
    phase = next((p for p in spec.phases if p.name == phase_name), None)
    if phase is None or not is_my_turn:
        return []
    action_type_names = {
        at.name: at for at in spec.action_types if at.name in phase.allowed_action_types and not at.is_message
    }
    return [
        AllowedAction(action_type=name, description=at.description, payload_schema=at.payload_schema)
        for name, at in action_type_names.items()
    ]
