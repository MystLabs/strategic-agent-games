"""Ultimatum game: N agents negotiate how to split R; private reservation values; payoff u = x − v."""

import random
from arena.core.match import Match, MatchStatus
from arena.spec import ActionTypeDef, GameSpec, OutcomeRule, Phase, TurnOrder
from arena.types import (
    Action,
    ActionError,
    ActionResult,
    TurnState,
    action_error,
    action_ok,
)

from arena.games.base import Game
from arena.games.utils import messages_visible_to, build_allowed_actions


GAME_ID = "ultimatum"


class UltimatumGame(Game):
    """Ultimatum: N agents negotiate how to split resource R.

    Each agent has a private reservation value v drawn uniformly from [0, reservation_max].
    Default reservation_max is R; can be set at instantiation.

    A proposer submits a split (shares dict mapping every agent to their share, summing to total).
    All other agents must accept for agreement; if any rejects, negotiation continues.

    Payoff on agreement: u_i = x_i − v_i, where x_i is agent i's share.
    If no agreement is reached within max_rounds, all agents receive 0.
    """

    def __init__(
        self,
        *,
        total: int = 100,
        max_rounds: int = 10,
        reservation_max: float | None = None,
        reservation_values: dict[str, float] | None = None,
        turn_order: TurnOrder = TurnOrder.ROUND_ROBIN,
    ) -> None:
        self._total = total
        self._max_rounds = max_rounds
        self._reservation_max = reservation_max
        self._fixed_reservation_values = reservation_values
        self._turn_order = turn_order

    @classmethod
    def from_params(cls, game_params: dict, agent_ids: list[str]) -> "UltimatumGame":
        total = game_params.get("total", 100)
        rv1 = game_params.get("rv1", 30)
        rv2 = game_params.get("rv2", 30)
        rv = {agent_ids[0]: rv1, agent_ids[1]: rv2}
        return cls(total=total, reservation_values=rv)

    def get_metadata(self) -> dict:
        return {
            **super().get_metadata(),
            "total": self._total,
            "max_rounds": self._max_rounds,
            "reservation_max": self._reservation_max,
            "reservation_values": self._fixed_reservation_values,
            "turn_order": self._turn_order.value,
        }

    def spec(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="Ultimatum",
            min_agents=2,
            description=(
                f"N agents negotiate how to split resource R={self._total}. "
                f"Each agent has a private reservation value v drawn uniformly from [0, {self._reservation_max if self._reservation_max is not None else self._total}]. "
                "A proposer submits a split (shares for every agent summing to R). "
                "All other agents must accept for agreement; if any rejects, negotiation continues. "
                "Payoff on agreement: u = x − v, where x is the agent's share. "
                f"If no agreement within {self._max_rounds} rounds, all get 0."
            ),
            phases=[
                Phase(
                    name="negotiation",
                    turn_order=self._turn_order,
                    allowed_action_types=["send_public_message", "send_private_message", "submit_offer", "accept", "reject", "pass", "message_only"],
                    max_rounds=self._max_rounds,
                ),
            ],
            action_types=[
                ActionTypeDef(
                    name="submit_offer",
                    description="Propose a split: shares dict mapping each agent_id to their share (must sum to total)",
                    payload_schema={"shares": {"type": "object", "description": "mapping of agent_id to share amount"}},
                    is_message=False,
                ),
                ActionTypeDef(name="accept", description="Accept current offer", payload_schema={}, is_message=False),
                ActionTypeDef(name="reject", description="Reject current offer (clears pending acceptances)", payload_schema={}, is_message=False),
                ActionTypeDef(name="pass", description="Only send messages this turn; pass the turn", payload_schema={}, is_message=False),
                ActionTypeDef(name="message_only", description="Only send messages; do not advance turn; other agents will be pinged to respond", payload_schema={}, is_message=False),
            ],
            outcome_rule=OutcomeRule.AGREEMENT,
            initial_game_state={
                "total": self._total,
                "current_offer": None,
                "last_offer_by": None,
                "acceptances": {},
                "reservation_values": None,
                "action_history": [],
            },
        )

    def _ensure_reservation_values(self, match: Match) -> None:
        if match.game_state.get("reservation_values") is not None:
            return
        if self._fixed_reservation_values is not None:
            match.game_state["reservation_values"] = dict(self._fixed_reservation_values)
            return
        total = match.game_state.get("total", self._total)
        v_max = total if self._reservation_max is None else self._reservation_max
        rng = random.Random(f"{match.match_id}")
        vals = [rng.uniform(0, v_max) for _ in match.agent_ids]
        match.game_state["reservation_values"] = dict(zip(match.agent_ids, vals))

    def _visible_game_state(self, match: Match, agent_id: str) -> dict:
        g = match.game_state
        out: dict = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
            "total": g.get("total", self._total),
            "current_offer": g.get("current_offer"),
            "last_offer_by": g.get("last_offer_by"),
            "acceptances": g.get("acceptances", {}),
        }
        rv = g.get("reservation_values")
        if rv and agent_id in rv:
            out["my_reservation_value"] = rv[agent_id]
        out["action_history"] = g.get("action_history", [])
        return out

    def compute_turn_state(self, match: Match, agent_id: str) -> TurnState | None:
        if match.game_id != GAME_ID:
            return None
        if match.status != MatchStatus.RUNNING:
            return self._not_running_turn_state(match, agent_id)
        self._ensure_reservation_values(match)
        phase_name, current_turn_agent_id, is_my_turn = self._get_phase_and_turn_info(match, agent_id)
        messages = messages_visible_to(match.messages, agent_id)
        allowed_actions = build_allowed_actions(match.spec, phase_name, is_my_turn)
        last_offer_by = match.game_state.get("last_offer_by")
        if last_offer_by == agent_id:
            allowed_actions = [a for a in allowed_actions if a.action_type != "accept"]
        return TurnState(
            match_id=match.match_id,
            game_id=match.game_id,
            agent_id=agent_id,
            phase=phase_name,
            is_my_turn=is_my_turn,
            current_turn_agent_id=current_turn_agent_id,
            game_state=self._visible_game_state(match, agent_id),
            messages=messages,
            allowed_actions=allowed_actions,
            game_over=(match.status == MatchStatus.FINISHED),
            outcome=match.outcome,
        )

    def _advance_turn_and_check_rounds(self, match: Match) -> None:
        n = len(match.agent_ids)
        if n == 0:
            return
        phase = match.spec.phases[match.current_phase_index] if match.spec.phases else None
        # Always rotate turn index so the runner cycles through agents.
        match.current_turn_index = (match.current_turn_index + 1) % n
        if match.current_turn_index == 0:
            match.current_round += 1
        if phase and phase.max_rounds is not None and match.current_round >= phase.max_rounds:
            match.outcome = {
                "payoffs": [{"agent_id": aid, "utility": 0.0} for aid in match.agent_ids],
                "reason": "max_rounds_exceeded",
            }
            match.status = MatchStatus.FINISHED

    def _is_random(self, match: Match) -> bool:
        phase = match.spec.phases[match.current_phase_index] if match.spec.phases else None
        return phase is not None and phase.turn_order == TurnOrder.RANDOM

    def apply_action(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        err = self._check_apply_preconditions(match, agent_id, GAME_ID)
        if err is not None:
            return err
        phase = match.spec.phases[match.current_phase_index] if match.spec.phases else None
        if not phase or phase.name != "negotiation":
            return action_error(ActionError.MATCH_NOT_RUNNING, "Not in negotiation phase")
        n = len(match.agent_ids)
        if n == 0:
            return action_error(ActionError.MATCH_NOT_RUNNING, "No agents in match")
        self._ensure_reservation_values(match)
        is_random = self._is_random(match)
        if not is_random:
            current_turn_agent_id = match.agent_ids[match.current_turn_index]
            if agent_id != current_turn_agent_id:
                return action_error(ActionError.NOT_YOUR_TURN, f"It is {current_turn_agent_id}'s turn")
        total = match.game_state.get("total", self._total)

        if action.action_type == "submit_offer":
            shares = action.payload.get("shares")
            if shares is None:
                return action_error(ActionError.INVALID_PAYLOAD, "shares is required")
            if not isinstance(shares, dict):
                return action_error(ActionError.INVALID_PAYLOAD, "shares must be an object mapping agent_id to share")
            # Validate all agents are present
            for aid in match.agent_ids:
                if aid not in shares:
                    return action_error(ActionError.INVALID_PAYLOAD, f"shares must include agent {aid}")
            # Validate numeric values in range
            parsed: dict[str, float] = {}
            for aid, val in shares.items():
                if aid not in match.agent_ids:
                    return action_error(ActionError.INVALID_PAYLOAD, f"Unknown agent {aid} in shares")
                try:
                    parsed[aid] = float(val)
                except (TypeError, ValueError):
                    return action_error(ActionError.INVALID_PAYLOAD, f"Share for {aid} must be a number")
                if parsed[aid] < 0:
                    return action_error(ActionError.INVALID_PAYLOAD, f"Share for {aid} must be >= 0")
            # Validate sum equals total
            share_sum = sum(parsed.values())
            if abs(share_sum - total) > 0.01:
                return action_error(ActionError.INVALID_PAYLOAD, f"Shares must sum to {total}, got {share_sum}")
            match.game_state["current_offer"] = parsed
            match.game_state["last_offer_by"] = agent_id
            match.game_state["acceptances"] = {}  # reset acceptances on new offer
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "submit_offer", "shares": parsed, "round": match.current_round}
            )
            self._advance_turn_and_check_rounds(match)
            return action_ok()

        if action.action_type == "accept":
            current_offer = match.game_state.get("current_offer")
            last_offer_by = match.game_state.get("last_offer_by")
            if current_offer is None or last_offer_by is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No active offer to accept")
            if last_offer_by == agent_id:
                return action_error(ActionError.GAME_RULE_VIOLATION, "Cannot accept your own offer")
            # Record this agent's acceptance
            acceptances = match.game_state.setdefault("acceptances", {})
            acceptances[agent_id] = True
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "accept", "round": match.current_round}
            )
            # Check if all non-proposers have accepted
            non_proposers = [aid for aid in match.agent_ids if aid != last_offer_by]
            if all(acceptances.get(aid) for aid in non_proposers):
                # Agreement reached — compute payoffs
                rv = match.game_state.get("reservation_values") or {}
                payoffs = []
                for aid in match.agent_ids:
                    share = float(current_offer[aid])
                    v = rv.get(aid, 0)
                    payoffs.append({
                        "agent_id": aid,
                        "share": share,
                        "utility": round(share - v, 2),
                    })
                match.outcome = {
                    "payoffs": payoffs,
                    "reason": "agreement",
                    "split": current_offer,
                }
                match.status = MatchStatus.FINISHED
            else:
                self._advance_turn_and_check_rounds(match)
            return action_ok()

        if action.action_type == "reject":
            match.game_state["acceptances"] = {}  # clear pending acceptances
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "reject", "round": match.current_round}
            )
            self._advance_turn_and_check_rounds(match)
            return action_ok()

        if action.action_type == "pass":
            self._advance_turn(match)
            return action_ok()

        if action.action_type == "message_only":
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "message_only", "round": match.current_round, "advances_turn": False}
            )
            return action_ok()

        return action_error(ActionError.INVALID_ACTION_TYPE, f"Unknown action type: {action.action_type}")

    def compute_outcome(self, match: Match) -> dict | None:
        if match.status == MatchStatus.FINISHED and match.outcome is not None:
            return match.outcome
        return None
