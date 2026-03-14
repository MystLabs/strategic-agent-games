"""First-price sealed-bid auction: N bidders chat, then submit sealed bids. Highest bid wins, pays own bid."""

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


GAME_ID = "first-price-auction"


class FirstPriceAuctionGame(Game):
    """First-price sealed-bid auction: N bidders each have a private valuation.

    They can chat via public or private messages, then submit sealed bids.
    Highest bid wins and pays own bid. Utility: winner = valuation - bid, losers = 0.
    If max_rounds exceeded without all bids, everyone gets utility 0.
    """

    def __init__(
        self,
        *,
        max_rounds: int = 10,
        valuations: dict[str, float] | None = None,
        turn_order: TurnOrder = TurnOrder.ROUND_ROBIN,
    ) -> None:
        self._max_rounds = max_rounds
        self._fixed_valuations = valuations
        self._turn_order = turn_order

    @classmethod
    def from_params(cls, game_params: dict, agent_ids: list[str]) -> "FirstPriceAuctionGame":
        rv1 = game_params.get("rv1", 30)
        rv2 = game_params.get("rv2", 30)
        vals = {agent_ids[0]: rv1, agent_ids[1]: rv2}
        return cls(valuations=vals)

    def get_metadata(self) -> dict:
        return {
            **super().get_metadata(),
            "max_rounds": self._max_rounds,
            "valuations": self._fixed_valuations,
            "turn_order": self._turn_order.value,
        }

    def spec(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="First-price sealed-bid auction",
            min_agents=2,
            description=(
                "N bidders each have a private valuation drawn uniformly from [0, 100]. "
                "They can chat (public or private messages) before bidding. "
                "Each submits one sealed bid (irreversible). "
                "Highest bid wins and pays own bid. Ties broken randomly. "
                f"Utility: winner = valuation − bid, losers = 0. "
                f"If not all bids submitted within {self._max_rounds} rounds, everyone gets 0."
            ),
            phases=[
                Phase(
                    name="auction",
                    turn_order=self._turn_order,
                    allowed_action_types=["submit_bid", "pass", "message_only"],
                    max_rounds=self._max_rounds,
                ),
            ],
            action_types=[
                ActionTypeDef(
                    name="submit_bid",
                    description="Submit a sealed bid (irreversible, once per agent)",
                    payload_schema={"bid": {"type": "number"}},
                    is_message=False,
                ),
                ActionTypeDef(name="pass", description="Pass the turn to the next agent", payload_schema={}, is_message=False),
                ActionTypeDef(name="message_only", description="Only send messages; do not advance turn", payload_schema={}, is_message=False),
            ],
            outcome_rule=OutcomeRule.ENGINE,
            initial_game_state={
                "bids": {},
                "valuations": None,
                "action_history": [],
            },
        )

    def _ensure_valuations(self, match: Match) -> None:
        if match.game_state.get("valuations") is not None:
            return
        if self._fixed_valuations is not None:
            # If the fixed valuation keys don't match the actual agent IDs,
            # map them positionally (first valuation → first agent, etc.)
            if set(self._fixed_valuations.keys()) == set(match.agent_ids):
                match.game_state["valuations"] = dict(self._fixed_valuations)
            else:
                vals = list(self._fixed_valuations.values())
                match.game_state["valuations"] = dict(zip(match.agent_ids, vals))
            return
        rng = random.Random(f"{match.match_id}")
        vals = [round(rng.uniform(0, 100), 2) for _ in match.agent_ids]
        match.game_state["valuations"] = dict(zip(match.agent_ids, vals))

    def _visible_game_state(self, match: Match, agent_id: str) -> dict:
        g = match.game_state
        valuations = g.get("valuations") or {}
        bids = g.get("bids") or {}
        opponent_ids = [aid for aid in match.agent_ids if aid != agent_id]
        out: dict = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
        }
        if agent_id in valuations:
            out["my_valuation"] = valuations[agent_id]
        out["my_bid"] = bids.get(agent_id)
        out["num_bidders"] = len(match.agent_ids)
        out["opponents_with_bid"] = [oid for oid in opponent_ids if oid in bids]
        out["num_bids_submitted"] = len(bids)
        out["action_history"] = g.get("action_history", [])
        return out

    def compute_turn_state(self, match: Match, agent_id: str) -> TurnState | None:
        if match.game_id != GAME_ID:
            return None
        if match.status != MatchStatus.RUNNING:
            return self._not_running_turn_state(match, agent_id)
        self._ensure_valuations(match)
        phase_name, current_turn_agent_id, is_my_turn = self._get_phase_and_turn_info(match, agent_id)
        messages = messages_visible_to(match.messages, agent_id)
        allowed_actions = build_allowed_actions(match.spec, phase_name, is_my_turn)
        # If agent already submitted a bid, remove submit_bid from allowed actions
        bids = match.game_state.get("bids") or {}
        if agent_id in bids:
            allowed_actions = [a for a in allowed_actions if a.action_type != "submit_bid"]
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
        # Always rotate turn index — the runner uses it to schedule which agent
        # to call next. In RANDOM mode the game doesn't *enforce* turn order, but
        # we still cycle so every agent gets prompted.
        match.current_turn_index = (match.current_turn_index + 1) % n
        if match.current_turn_index == 0:
            match.current_round += 1
        phase = match.spec.phases[match.current_phase_index] if match.spec.phases else None
        if phase and phase.max_rounds is not None and match.current_round >= phase.max_rounds:
            match.outcome = {
                "payoffs": [{"agent_id": aid, "utility": 0.0} for aid in match.agent_ids],
                "reason": "max_rounds_exceeded",
            }
            match.status = MatchStatus.FINISHED

    def _resolve_auction(self, match: Match) -> None:
        bids = match.game_state["bids"]
        valuations = match.game_state["valuations"]
        agents = list(bids.keys())
        bid_values = [(aid, bids[aid]) for aid in agents]
        max_bid = max(b for _, b in bid_values)
        top_bidders = [aid for aid, b in bid_values if b == max_bid]
        if len(top_bidders) == 1:
            winner = top_bidders[0]
        else:
            rng = random.Random(f"{match.match_id}_tiebreak")
            winner = rng.choice(top_bidders)
        payoffs = []
        for aid in match.agent_ids:
            bid = bids[aid]
            if aid == winner:
                utility = round(valuations[aid] - bid, 2)
            else:
                utility = 0.0
            payoffs.append({"agent_id": aid, "bid": bid, "utility": utility})
        match.outcome = {
            "payoffs": payoffs,
            "reason": "auction_resolved",
            "winner": winner,
        }
        match.status = MatchStatus.FINISHED

    def apply_action(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        err = self._check_apply_preconditions(match, agent_id, GAME_ID)
        if err is not None:
            return err
        phase = match.spec.phases[match.current_phase_index] if match.spec.phases else None
        if not phase or phase.name != "auction":
            return action_error(ActionError.MATCH_NOT_RUNNING, "Not in auction phase")
        n = len(match.agent_ids)
        if n == 0:
            return action_error(ActionError.MATCH_NOT_RUNNING, "No agents in match")
        is_random = phase.turn_order == TurnOrder.RANDOM
        if not is_random:
            current_turn_agent_id = match.agent_ids[match.current_turn_index]
            if agent_id != current_turn_agent_id:
                return action_error(ActionError.NOT_YOUR_TURN, f"It is {current_turn_agent_id}'s turn")

        if action.action_type == "submit_bid":
            bids = match.game_state.get("bids") or {}
            if agent_id in bids:
                return action_error(ActionError.GAME_RULE_VIOLATION, "You have already submitted a bid")
            bid = action.payload.get("bid")
            if bid is None:
                return action_error(ActionError.INVALID_PAYLOAD, "bid is required")
            try:
                bid = float(bid)
            except (TypeError, ValueError):
                return action_error(ActionError.INVALID_PAYLOAD, "bid must be a number")
            if bid < 0:
                return action_error(ActionError.INVALID_PAYLOAD, "bid must be >= 0")
            bids[agent_id] = bid
            match.game_state["bids"] = bids
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "submit_bid", "round": match.current_round}
            )
            # Check if all agents have bid
            if all(aid in bids for aid in match.agent_ids):
                self._resolve_auction(match)
                return action_ok()
            self._advance_turn_and_check_rounds(match)
            return action_ok()

        if action.action_type == "pass":
            self._advance_turn_and_check_rounds(match)
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
