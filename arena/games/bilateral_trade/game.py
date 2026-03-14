"""Bilateral trade: initiator and provider(s) negotiate scope & price, then deliver & verify.

With 2 agents the game behaves as a classic bilateral negotiation.
With 3+ agents the game becomes competitive: multiple providers submit proposals
and the initiator selects one.

Modes:
  - "full" (default): full bilateral trade with request/negotiate/deliver/verify.
  - "price_only": simplified — fixed scope, single negotiate phase, price-only proposals.
"""

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


GAME_ID = "bilateral-trade"


class BilateralTradeGame(Game):
    """Bilateral trade: an initiator and one or more providers negotiate scope & price.

    With 2 agents: classic bilateral trade — both parties alternate proposals.
    With 3+ agents: competitive mode — providers submit independent proposals,
    the initiator selects one winner.

    On agreement the (selected) provider delivers; the initiator verifies and
    releases payment.
    Dispute resolution: no_payment (default) or split (50/50 of agreed price).
    """

    def __init__(
        self,
        *,
        dispute_resolution: str = "no_payment",
        negotiate_turn_order: str = "round_robin",
        mode: str = "full",
        fixed_scope: str = "",
        max_budget: float = 100,
        reservation_values: dict[str, float] | None = None,
    ) -> None:
        if mode not in ("full", "price_only"):
            raise ValueError(f"mode must be 'full' or 'price_only', got {mode!r}")
        if dispute_resolution not in ("no_payment", "split"):
            raise ValueError(f"dispute_resolution must be 'no_payment' or 'split', got {dispute_resolution!r}")
        if negotiate_turn_order not in ("round_robin", "random"):
            raise ValueError(f"negotiate_turn_order must be 'round_robin' or 'random', got {negotiate_turn_order!r}")
        self._mode = mode
        self._dispute_resolution = dispute_resolution
        self._negotiate_turn_order = negotiate_turn_order
        self._fixed_scope = fixed_scope
        self._max_budget = max_budget
        self._reservation_values = reservation_values

    @classmethod
    def from_params(cls, game_params: dict, agent_ids: list[str]) -> "BilateralTradeGame":
        buyer_rv = game_params.get("buyer_rv", 80)
        seller_rv = game_params.get("seller_rv", 40)
        rv = {agent_ids[0]: buyer_rv, agent_ids[1]: seller_rv}
        return cls(
            mode="price_only",
            max_budget=buyer_rv,
            reservation_values=rv,
            fixed_scope="A service",
        )

    def get_metadata(self) -> dict:
        meta = {
            **super().get_metadata(),
            "mode": self._mode,
            "dispute_resolution": self._dispute_resolution,
            "negotiate_turn_order": self._negotiate_turn_order,
            "max_budget": self._max_budget,
        }
        if self._fixed_scope:
            meta["fixed_scope"] = self._fixed_scope
        if self._reservation_values:
            meta["reservation_values"] = self._reservation_values
        return meta

    def spec(self) -> GameSpec:
        if self._mode == "price_only":
            return self._spec_price_only()
        return self._spec_full()

    def _spec_price_only(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="Bilateral Trade (Price Only)",
            min_agents=2,
            description=(
                "A buyer and a seller negotiate a price for a predefined task. "
                "The seller proposes prices; the buyer accepts or rejects. "
                f"Task: {self._fixed_scope}. Max budget: {self._max_budget}."
            ),
            phases=[
                Phase(
                    name="negotiate",
                    turn_order=TurnOrder.ROUND_ROBIN,
                    allowed_action_types=["propose", "accept_proposal", "reject_and_exit", "pass", "message_only"],
                    max_rounds=100,
                ),
            ],
            action_types=[
                ActionTypeDef(name="propose", description="Propose a price for the task", payload_schema={"price": {"type": "number", "min": 0}}),
                ActionTypeDef(name="accept_proposal", description="Accept the other side's proposed price", payload_schema={}),
                ActionTypeDef(name="reject_and_exit", description="Walk away; game ends with payoffs 0", payload_schema={"reason": {"type": "string"}}),
                ActionTypeDef(name="pass", description="Skip your turn without acting", payload_schema={}),
                ActionTypeDef(name="message_only", description="Only send messages; do not advance turn", payload_schema={}),
            ],
            outcome_rule=OutcomeRule.AGREEMENT,
            initial_game_state={
                "proposal": None,
                "agreement": None,
                "action_history": [],
                "resolved": False,
            },
        )

    def _spec_full(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="Bilateral Trade",
            min_agents=2,
            description=(
                "An initiator and one or more providers negotiate scope and price. "
                "With 2 agents: classic bilateral trade. With 3+: providers compete. "
                f"Dispute resolution: {self._dispute_resolution}."
            ),
            phases=[
                Phase(name="request", turn_order=TurnOrder.ROUND_ROBIN, allowed_action_types=["post_request", "message_only"], max_rounds=2),
                Phase(name="negotiate", turn_order=TurnOrder.RANDOM if self._negotiate_turn_order == "random" else TurnOrder.ROUND_ROBIN, allowed_action_types=["propose", "accept_proposal", "reject_and_exit", "pass", "message_only"], max_rounds=8),
                Phase(name="deliver", turn_order=TurnOrder.ROUND_ROBIN, allowed_action_types=["submit_deliverable", "message_only"], max_rounds=3),
                Phase(name="verify", turn_order=TurnOrder.ROUND_ROBIN, allowed_action_types=["accept_delivery", "dispute_delivery", "message_only"], max_rounds=2),
            ],
            action_types=[
                ActionTypeDef(name="post_request", description="Post what you need and your max budget (initiator only)", payload_schema={"description": {"type": "string"}, "max_budget": {"type": "number", "min": 0}}),
                ActionTypeDef(name="propose", description="Propose scope and price (must be <= max_budget)", payload_schema={"scope": {"type": "string"}, "price": {"type": "number", "min": 0}}),
                ActionTypeDef(name="accept_proposal", description="Accept a proposal (with 3+ agents, specify provider_id)", payload_schema={"provider_id": {"type": "string"}}),
                ActionTypeDef(name="reject_and_exit", description="Walk away; game ends with payoffs 0", payload_schema={"reason": {"type": "string"}}),
                ActionTypeDef(name="pass", description="Skip your turn without acting", payload_schema={}),
                ActionTypeDef(name="submit_deliverable", description="Submit the deliverable (provider only)", payload_schema={"content": {"type": "string"}}),
                ActionTypeDef(name="accept_delivery", description="Accept delivery and release payment (initiator only)", payload_schema={}),
                ActionTypeDef(name="dispute_delivery", description="Dispute the delivery (initiator only)", payload_schema={"reason": {"type": "string"}}),
                ActionTypeDef(name="message_only", description="Only send messages; do not advance turn", payload_schema={}),
            ],
            outcome_rule=OutcomeRule.AGREEMENT,
            initial_game_state={
                "request": None,
                "proposal": None,
                "proposals": {},
                "active_providers": [],
                "agreement": None,
                "selected_provider": None,
                "deliverable": None,
                "delivery_accepted": None,
                "action_history": [],
                "resolved": False,
            },
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _is_competitive(self, match: Match) -> bool:
        """True when 3+ agents (competitive mode with multiple providers)."""
        return len(match.agent_ids) > 2

    def _role(self, match: Match, agent_id: str) -> str:
        if self._mode == "price_only":
            return "buyer" if agent_id == match.agent_ids[0] else "seller"
        return "initiator" if agent_id == match.agent_ids[0] else "provider"

    def _ensure_reservation_values(self, match: Match) -> None:
        if match.game_state.get("reservation_values") is not None:
            return
        if self._reservation_values:
            match.game_state["reservation_values"] = dict(self._reservation_values)
        else:
            match.game_state["reservation_values"] = {aid: 0.0 for aid in match.agent_ids}

    def _phase(self, match: Match) -> Phase | None:
        if match.current_phase_index < len(match.spec.phases):
            return match.spec.phases[match.current_phase_index]
        return None

    def _advance_phase(self, match: Match) -> None:
        match.current_phase_index += 1
        match.current_round = 0
        phase = self._phase(match)
        if phase is not None and phase.name == "deliver":
            selected = match.game_state.get("selected_provider")
            if selected and selected in match.agent_ids:
                match.current_turn_index = match.agent_ids.index(selected)
            else:
                match.current_turn_index = 1  # fallback for 2-agent
        elif phase is not None and phase.name == "negotiate" and self._is_competitive(match):
            match.current_turn_index = 1  # first provider — initiator joins when proposals exist
        else:
            match.current_turn_index = 0

    def _zero_payoffs(self, match: Match) -> list[dict]:
        return [{"agent_id": aid, "utility": 0.0} for aid in match.agent_ids]

    def _finish(self, match: Match, payoffs: list[dict], reason: str) -> None:
        match.outcome = {"payoffs": payoffs, "reason": reason}
        match.status = MatchStatus.FINISHED
        match.game_state["resolved"] = True

    def _is_active_agent(self, match: Match, agent_id: str) -> bool:
        phase = self._phase(match)
        if phase is None:
            return False
        if phase.name == "negotiate":
            if self._negotiate_turn_order == "random":
                if not self._is_competitive(match):
                    # 2-agent random: both can act
                    return True
                # competitive random: any active provider OR initiator (if proposals exist)
                g = match.game_state
                role = self._role(match, agent_id)
                if role == "provider":
                    return agent_id in g.get("active_providers", [])
                # initiator: only after at least one proposal
                return bool(g.get("proposals"))
            # round_robin: strict turn gating
            n = len(match.agent_ids)
            idx = match.current_turn_index % n if n else 0
            return match.agent_ids[idx] == agent_id
        role = self._role(match, agent_id)
        if phase.name == "request":
            return role == "initiator"
        if phase.name == "deliver":
            selected = match.game_state.get("selected_provider")
            if selected:
                return agent_id == selected
            return role == "provider"
        if phase.name == "verify":
            return role == "initiator"
        return False

    def _current_turn_agent_id(self, match: Match) -> str | None:
        phase = self._phase(match)
        if phase is None or not match.agent_ids:
            return None
        if phase.name == "negotiate":
            n = len(match.agent_ids)
            return match.agent_ids[match.current_turn_index % n]
        if phase.name in ("request", "verify"):
            return match.agent_ids[0]  # initiator
        if phase.name == "deliver":
            selected = match.game_state.get("selected_provider")
            return selected or match.agent_ids[1]
        return None

    def _advance_negotiate_turn(self, match: Match) -> None:
        n = len(match.agent_ids)
        if n == 0:
            return
        if self._is_competitive(match):
            # Skip exited providers and skip initiator until proposals exist
            g = match.game_state
            active = g.get("active_providers", [])
            has_proposals = bool(g.get("proposals"))
            for _ in range(n):
                match.current_turn_index = (match.current_turn_index + 1) % n
                if match.current_turn_index == 0:
                    match.current_round += 1
                candidate = match.agent_ids[match.current_turn_index]
                if candidate == match.agent_ids[0]:
                    if has_proposals:
                        break  # initiator gets turn only when proposals exist
                elif candidate in active:
                    break
        else:
            match.current_turn_index = (match.current_turn_index + 1) % n
            if match.current_turn_index == 0:
                match.current_round += 1
        phase = self._phase(match)
        if phase and phase.max_rounds is not None and match.current_round >= phase.max_rounds:
            self._finish(match, self._zero_payoffs(match), "max_rounds_exceeded")

    def _visible_game_state(self, match: Match, agent_id: str | None = None) -> dict:
        if self._mode == "price_only":
            return self._visible_game_state_price_only(match, agent_id)

        g = match.game_state
        initiator_id = match.agent_ids[0] if match.agent_ids else None
        provider_ids = match.agent_ids[1:] if len(match.agent_ids) > 1 else []
        state = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
            "initiator": initiator_id,
            "providers": provider_ids,
            "my_role": "initiator" if agent_id == initiator_id else "provider",
            "request": g.get("request"),
            "proposal": g.get("proposal"),
            "agreement": g.get("agreement"),
            "deliverable": g.get("deliverable"),
            "delivery_accepted": g.get("delivery_accepted"),
            "action_history": g.get("action_history", []),
        }
        if self._is_competitive(match):
            all_proposals = g.get("proposals", {})
            if agent_id and self._role(match, agent_id) == "provider":
                # Providers only see their own proposal (sealed bids)
                own = all_proposals.get(agent_id)
                state["proposals"] = {agent_id: own} if own else {}
            else:
                # Initiator sees all proposals
                state["proposals"] = all_proposals
            state["active_providers"] = g.get("active_providers", [])
            state["selected_provider"] = g.get("selected_provider")
        return state

    def _visible_game_state_price_only(self, match: Match, agent_id: str | None = None) -> dict:
        self._ensure_reservation_values(match)
        g = match.game_state
        buyer_id = match.agent_ids[0] if match.agent_ids else None
        seller_id = match.agent_ids[1] if len(match.agent_ids) > 1 else None
        rv = g.get("reservation_values", {})
        role = self._role(match, agent_id) if agent_id else "unknown"
        state = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
            "buyer": buyer_id,
            "seller": seller_id,
            "my_role": role,
            "fixed_scope": self._fixed_scope,
            "proposal": g.get("proposal"),
            "agreement": g.get("agreement"),
            "action_history": g.get("action_history", []),
        }
        # Only buyer sees max_budget (it equals buyer_rv — private info)
        if role == "buyer":
            state["max_budget"] = self._max_budget
        if agent_id and agent_id in rv:
            state["my_reservation_value"] = rv[agent_id]
        return state

    # ── Game interface ────────────────────────────────────────────────────────

    def compute_turn_state(self, match: Match, agent_id: str) -> TurnState | None:
        if match.game_id != GAME_ID:
            return None
        if match.status != MatchStatus.RUNNING:
            return self._not_running_turn_state(match, agent_id)

        if self._mode == "price_only":
            return self._compute_turn_state_price_only(match, agent_id)

        phase = self._phase(match)
        phase_name = phase.name if phase else ""
        is_my_turn = self._is_active_agent(match, agent_id)
        allowed_actions = build_allowed_actions(match.spec, phase_name, is_my_turn)

        # Filter by preconditions
        g = match.game_state
        role = self._role(match, agent_id)

        if phase_name == "request":
            if role != "initiator" or g.get("request") is not None:
                allowed_actions = [a for a in allowed_actions if a.action_type != "post_request"]

        elif phase_name == "negotiate":
            if self._is_competitive(match):
                # Competitive: only providers propose, only initiator accepts
                if role != "provider":
                    allowed_actions = [a for a in allowed_actions if a.action_type != "propose"]
                if role != "initiator" or not g.get("proposals"):
                    allowed_actions = [a for a in allowed_actions if a.action_type != "accept_proposal"]
                if g.get("request") is None:
                    allowed_actions = [a for a in allowed_actions if a.action_type != "propose"]
            else:
                # 2-agent: both can propose, can't accept own proposal
                proposal = g.get("proposal")
                if proposal is None or proposal.get("proposed_by") == agent_id:
                    allowed_actions = [a for a in allowed_actions if a.action_type != "accept_proposal"]
                if g.get("request") is None:
                    allowed_actions = [a for a in allowed_actions if a.action_type != "propose"]

        elif phase_name == "deliver":
            if self._is_competitive(match):
                if agent_id != g.get("selected_provider") or g.get("deliverable") is not None:
                    allowed_actions = [a for a in allowed_actions if a.action_type != "submit_deliverable"]
            else:
                if role != "provider" or g.get("deliverable") is not None:
                    allowed_actions = [a for a in allowed_actions if a.action_type != "submit_deliverable"]

        elif phase_name == "verify":
            if role != "initiator" or g.get("deliverable") is None:
                allowed_actions = [a for a in allowed_actions if a.action_type not in ("accept_delivery", "dispute_delivery")]

        return TurnState(
            match_id=match.match_id,
            game_id=match.game_id,
            agent_id=agent_id,
            phase=phase_name,
            is_my_turn=is_my_turn,
            current_turn_agent_id=self._current_turn_agent_id(match),
            game_state=self._visible_game_state(match, agent_id),
            messages=messages_visible_to(match.messages, agent_id),
            allowed_actions=allowed_actions,
            game_over=False,
            outcome=None,
        )

    def _compute_turn_state_price_only(self, match: Match, agent_id: str) -> TurnState:
        self._ensure_reservation_values(match)
        phase = self._phase(match)
        phase_name = phase.name if phase else "negotiate"
        n = len(match.agent_ids)
        idx = match.current_turn_index % n if n else 0
        current_turn_agent_id = match.agent_ids[idx]
        is_my_turn = current_turn_agent_id == agent_id
        allowed_actions = build_allowed_actions(match.spec, phase_name, is_my_turn)

        role = self._role(match, agent_id)
        g = match.game_state
        proposal = g.get("proposal")

        # Both buyer and seller can propose prices (like ultimatum).
        # Can only accept/reject the OTHER side's proposal.
        if proposal is None or proposal.get("proposed_by") == agent_id:
            allowed_actions = [a for a in allowed_actions if a.action_type not in ("accept_proposal",)]
        # Can always reject_and_exit
        # Can always propose (counter-propose)

        return TurnState(
            match_id=match.match_id,
            game_id=match.game_id,
            agent_id=agent_id,
            phase=phase_name,
            is_my_turn=is_my_turn,
            current_turn_agent_id=current_turn_agent_id,
            game_state=self._visible_game_state(match, agent_id),
            messages=messages_visible_to(match.messages, agent_id),
            allowed_actions=allowed_actions,
            game_over=False,
            outcome=None,
        )

    def apply_action(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        err = self._check_apply_preconditions(match, agent_id, GAME_ID)
        if err is not None:
            return err

        if self._mode == "price_only":
            return self._apply_action_price_only(match, agent_id, action)

        phase = self._phase(match)
        if phase is None:
            return action_error(ActionError.MATCH_NOT_RUNNING, "No active phase")

        g = match.game_state
        role = self._role(match, agent_id)
        atype = action.action_type
        competitive = self._is_competitive(match)

        # Turn check (message still requires turn, like message_only in other games)
        if not self._is_active_agent(match, agent_id):
            return action_error(ActionError.NOT_YOUR_TURN, f"It is {self._current_turn_agent_id(match)}'s turn")

        # Phase-level guard
        if atype not in phase.allowed_action_types:
            return action_error(ActionError.INVALID_ACTION_TYPE, f"{atype} not allowed in {phase.name} phase")

        # ── message_only (never advances turn) ───────────────────────────────
        if atype == "message_only":
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "message_only", "round": match.current_round, "phase": phase.name, "advances_turn": False}
            )
            return action_ok()

        # ── pass (advances turn in negotiate) ────────────────────────────────
        if atype == "pass":
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "pass", "round": match.current_round, "phase": phase.name}
            )
            if phase.name == "negotiate":
                self._advance_negotiate_turn(match)
            return action_ok()

        # ── request phase ────────────────────────────────────────────────────
        if atype == "post_request":
            if role != "initiator":
                return action_error(ActionError.GAME_RULE_VIOLATION, "Only initiator can post request")
            if g.get("request") is not None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "Request already posted")
            desc = action.payload.get("description")
            max_budget = action.payload.get("max_budget")
            if not desc:
                return action_error(ActionError.INVALID_PAYLOAD, "description is required")
            if max_budget is None:
                return action_error(ActionError.INVALID_PAYLOAD, "max_budget is required")
            try:
                max_budget = float(max_budget)
            except (TypeError, ValueError):
                return action_error(ActionError.INVALID_PAYLOAD, "max_budget must be a number")
            if max_budget < 0:
                return action_error(ActionError.INVALID_PAYLOAD, "max_budget must be >= 0")
            g["request"] = {"description": desc, "max_budget": max_budget}
            if competitive:
                g["active_providers"] = list(match.agent_ids[1:])
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "post_request", "round": match.current_round, "phase": phase.name})
            self._advance_phase(match)
            return action_ok()

        # ── negotiate phase ──────────────────────────────────────────────────
        if atype == "propose":
            if competitive and role != "provider":
                return action_error(ActionError.GAME_RULE_VIOLATION, "Only providers can propose")
            if g.get("request") is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No request posted yet")
            scope = action.payload.get("scope")
            price = action.payload.get("price")
            if not scope:
                return action_error(ActionError.INVALID_PAYLOAD, "scope is required")
            if price is None:
                return action_error(ActionError.INVALID_PAYLOAD, "price is required")
            try:
                price = float(price)
            except (TypeError, ValueError):
                return action_error(ActionError.INVALID_PAYLOAD, "price must be a number")
            if price < 0:
                return action_error(ActionError.INVALID_PAYLOAD, "price must be >= 0")
            if price > g["request"]["max_budget"]:
                return action_error(ActionError.GAME_RULE_VIOLATION, f"price {price} exceeds max_budget {g['request']['max_budget']}")
            if competitive:
                g["proposals"][agent_id] = {"scope": scope, "price": price}
            else:
                g["proposal"] = {"scope": scope, "price": price, "proposed_by": agent_id}
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "propose", "scope": scope, "price": price, "round": match.current_round, "phase": phase.name})
            self._advance_negotiate_turn(match)
            return action_ok()

        if atype == "accept_proposal":
            if competitive:
                if role != "initiator":
                    return action_error(ActionError.GAME_RULE_VIOLATION, "Only initiator can accept a proposal")
                provider_id = action.payload.get("provider_id")
                if not provider_id:
                    return action_error(ActionError.INVALID_PAYLOAD, "provider_id is required")
                if provider_id not in g.get("active_providers", []):
                    return action_error(ActionError.GAME_RULE_VIOLATION, f"Provider {provider_id!r} is not an active provider")
                proposal = g.get("proposals", {}).get(provider_id)
                if proposal is None:
                    return action_error(ActionError.GAME_RULE_VIOLATION, f"Provider {provider_id!r} has not submitted a proposal")
                g["agreement"] = {"provider_id": provider_id, "scope": proposal["scope"], "price": proposal["price"]}
                g["selected_provider"] = provider_id
            else:
                proposal = g.get("proposal")
                if proposal is None:
                    return action_error(ActionError.GAME_RULE_VIOLATION, "No proposal to accept")
                if proposal.get("proposed_by") == agent_id:
                    return action_error(ActionError.GAME_RULE_VIOLATION, "Cannot accept your own proposal")
                g["agreement"] = dict(proposal)
                g["selected_provider"] = match.agent_ids[1]  # provider always delivers in 2-agent mode
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "accept_proposal", "round": match.current_round, "phase": phase.name})
            self._advance_phase(match)
            return action_ok()

        if atype == "reject_and_exit":
            reason = action.payload.get("reason", "")
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "reject_and_exit", "reason": reason, "round": match.current_round, "phase": phase.name})
            if competitive:
                if role == "initiator":
                    self._finish(match, self._zero_payoffs(match), "initiator_exited")
                else:
                    active = g.get("active_providers", [])
                    if agent_id in active:
                        active.remove(agent_id)
                    g.get("proposals", {}).pop(agent_id, None)
                    if not active:
                        self._finish(match, self._zero_payoffs(match), "all_providers_exited")
                    else:
                        self._advance_negotiate_turn(match)
            else:
                self._finish(match, self._zero_payoffs(match), "negotiation_failed")
            return action_ok()

        # ── deliver phase ────────────────────────────────────────────────────
        if atype == "submit_deliverable":
            if competitive:
                if agent_id != g.get("selected_provider"):
                    return action_error(ActionError.GAME_RULE_VIOLATION, "Only selected provider can submit deliverable")
            else:
                if role != "provider":
                    return action_error(ActionError.GAME_RULE_VIOLATION, "Only provider can submit deliverable")
            if g.get("agreement") is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No agreement reached")
            if g.get("deliverable") is not None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "Deliverable already submitted")
            content = action.payload.get("content")
            if not content:
                return action_error(ActionError.INVALID_PAYLOAD, "content is required")
            g["deliverable"] = content
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "submit_deliverable", "round": match.current_round, "phase": phase.name})
            self._advance_phase(match)
            return action_ok()

        # ── verify phase ─────────────────────────────────────────────────────
        if atype == "accept_delivery":
            if role != "initiator":
                return action_error(ActionError.GAME_RULE_VIOLATION, "Only initiator can accept delivery")
            if g.get("deliverable") is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No deliverable to verify")
            g["delivery_accepted"] = True
            price = g["agreement"]["price"]
            initiator_id = match.agent_ids[0]
            selected = g.get("selected_provider") or match.agent_ids[1]
            payoffs = []
            for aid in match.agent_ids:
                if aid == initiator_id:
                    payoffs.append({"agent_id": aid, "utility": round(-price, 2)})
                elif aid == selected:
                    payoffs.append({"agent_id": aid, "utility": round(price, 2)})
                else:
                    payoffs.append({"agent_id": aid, "utility": 0.0})
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "accept_delivery", "round": match.current_round, "phase": phase.name})
            self._finish(match, payoffs, "trade_completed")
            return action_ok()

        if atype == "dispute_delivery":
            if role != "initiator":
                return action_error(ActionError.GAME_RULE_VIOLATION, "Only initiator can dispute delivery")
            if g.get("deliverable") is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No deliverable to dispute")
            reason = action.payload.get("reason", "")
            g["delivery_accepted"] = False
            g.setdefault("action_history", []).append({"agent_id": agent_id, "action": "dispute_delivery", "reason": reason, "round": match.current_round, "phase": phase.name})
            if self._dispute_resolution == "split":
                price = g["agreement"]["price"]
                initiator_id = match.agent_ids[0]
                selected = g.get("selected_provider") or match.agent_ids[1]
                payoffs = []
                for aid in match.agent_ids:
                    if aid == initiator_id:
                        payoffs.append({"agent_id": aid, "utility": round(-price * 0.5, 2)})
                    elif aid == selected:
                        payoffs.append({"agent_id": aid, "utility": round(price * 0.5, 2)})
                    else:
                        payoffs.append({"agent_id": aid, "utility": 0.0})
                self._finish(match, payoffs, "delivery_disputed_split")
            else:
                self._finish(match, self._zero_payoffs(match), "delivery_disputed_no_payment")
            return action_ok()

        return action_error(ActionError.INVALID_ACTION_TYPE, f"Unknown action type: {atype}")

    # ── price_only mode apply_action ──────────────────────────────────────────

    def _apply_action_price_only(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        phase = self._phase(match)
        if phase is None:
            return action_error(ActionError.MATCH_NOT_RUNNING, "No active phase")

        self._ensure_reservation_values(match)
        g = match.game_state
        role = self._role(match, agent_id)
        atype = action.action_type

        # Turn check
        n = len(match.agent_ids)
        idx = match.current_turn_index % n if n else 0
        current = match.agent_ids[idx]
        if atype != "message_only" and agent_id != current:
            return action_error(ActionError.NOT_YOUR_TURN, f"It is {current}'s turn")

        if atype not in phase.allowed_action_types:
            return action_error(ActionError.INVALID_ACTION_TYPE, f"{atype} not allowed in {phase.name} phase")

        if atype == "message_only":
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "message_only", "round": match.current_round, "phase": phase.name, "advances_turn": False}
            )
            return action_ok()

        if atype == "pass":
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "pass", "round": match.current_round, "phase": phase.name}
            )
            self._advance_negotiate_turn(match)
            return action_ok()

        if atype == "propose":
            price = action.payload.get("price")
            if price is None:
                return action_error(ActionError.INVALID_PAYLOAD, "price is required")
            try:
                price = float(price)
            except (TypeError, ValueError):
                return action_error(ActionError.INVALID_PAYLOAD, "price must be a number")
            if price < 0:
                return action_error(ActionError.INVALID_PAYLOAD, "price must be >= 0")
            if price > self._max_budget:
                return action_error(ActionError.GAME_RULE_VIOLATION, f"price {price} exceeds max_budget {self._max_budget}")
            g["proposal"] = {"scope": self._fixed_scope, "price": price, "proposed_by": agent_id}
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "propose", "price": price, "round": match.current_round, "phase": phase.name}
            )
            self._advance_negotiate_turn(match)
            return action_ok()

        if atype == "accept_proposal":
            proposal = g.get("proposal")
            if proposal is None:
                return action_error(ActionError.GAME_RULE_VIOLATION, "No proposal to accept")
            if proposal.get("proposed_by") == agent_id:
                return action_error(ActionError.GAME_RULE_VIOLATION, "Cannot accept your own proposal")
            price = proposal["price"]
            g["agreement"] = {"scope": self._fixed_scope, "price": price}
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "accept_proposal", "round": match.current_round, "phase": phase.name}
            )
            # Compute payoffs: buyer utility = max_budget - price, seller utility = price - seller_RV
            rv = g.get("reservation_values", {})
            buyer_id = match.agent_ids[0]
            seller_id = match.agent_ids[1]
            payoffs = [
                {"agent_id": buyer_id, "utility": round(self._max_budget - price, 2)},
                {"agent_id": seller_id, "utility": round(price - rv.get(seller_id, 0), 2)},
            ]
            self._finish(match, payoffs, "trade_completed")
            return action_ok()

        if atype == "reject_and_exit":
            reason = action.payload.get("reason", "")
            g.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "reject_and_exit", "reason": reason, "round": match.current_round, "phase": phase.name}
            )
            self._finish(match, self._zero_payoffs(match), "negotiation_failed")
            return action_ok()

        return action_error(ActionError.INVALID_ACTION_TYPE, f"Unknown action type: {atype}")

    def compute_outcome(self, match: Match) -> dict | None:
        if match.status == MatchStatus.FINISHED and match.outcome is not None:
            return match.outcome
        return None
