"""Provision Point: collective resource pooling with coordinator and contributors.

Modes:
  - "full" (default): coordinator + contributors, announce → signal → commit phases.
  - "simple": no coordinator, all agents are equal contributors, single commit phase.

Roles (full mode): coordinator (index 0), contributors (indices 1, 2, …).
Phases (full mode): announce → signal → commit → (engine resolution).

Valuation modes:
  - "random" (default): each contributor's valuation is drawn uniformly at match start.
  - "fixed": valuations are set via the constructor (for controlled experiments).
  - "auto": contributors privately set their valuation via my_valuation field on signal/commit.
"""

from __future__ import annotations

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


GAME_ID = "provision-point"

_COORDINATOR = 0


class ProvisionPointGame(Game):
    """Provision Point: a coordinator proposes a collective project; contributors
    decide how much to commit.  If total commitments >= threshold the project is
    funded; otherwise all commitments are refunded.

    Roles (by agent index):
        0       = coordinator — announces the project
        1, 2, … = contributors — signal intent, then commit tokens

    Valuation modes:
        "random" — drawn uniformly from valuation_range at match start (default).
        "fixed"  — passed explicitly via *valuations* dict.
        "auto"   — contributors set my_valuation via signal_intent/submit_commitment payload.
    """

    def __init__(
        self,
        *,
        threshold: float = 100,
        endowment: float = 80,
        valuation_range: tuple[float, float] = (0, 150),
        allow_commitment_updates: bool = True,
        valuation_mode: str = "random",
        valuations: dict[str, float] | None = None,
        turn_order: TurnOrder = TurnOrder.ROUND_ROBIN,
        max_rounds_announce: int = 2,
        max_rounds_signal: int = 3,
        max_rounds_commit: int = 6,
        mode: str = "full",
    ) -> None:
        if mode not in ("full", "simple"):
            raise ValueError(f"mode must be 'full' or 'simple', got {mode!r}")
        # Backward compat: if valuations dict provided without explicit mode, infer "fixed"
        if valuations is not None and valuation_mode == "random":
            valuation_mode = "fixed"
        if valuation_mode not in ("random", "fixed", "auto"):
            raise ValueError(f"valuation_mode must be 'random', 'fixed', or 'auto', got {valuation_mode!r}")
        if valuation_mode == "fixed" and not valuations:
            raise ValueError("valuations dict required when valuation_mode='fixed'")

        self._mode = mode
        self._threshold = threshold
        self._endowment = endowment
        self._valuation_range = valuation_range
        self._allow_updates = allow_commitment_updates
        self._valuation_mode = valuation_mode
        self._fixed_valuations = valuations
        self._turn_order = turn_order
        self._max_rounds_announce = max_rounds_announce
        self._max_rounds_signal = max_rounds_signal
        self._max_rounds_commit = max_rounds_commit

    @classmethod
    def from_params(cls, game_params: dict, agent_ids: list[str]) -> "ProvisionPointGame":
        threshold = game_params.get("threshold", 100)
        rv1 = game_params.get("rv1", 70)
        rv2 = game_params.get("rv2", 70)
        vals = {agent_ids[0]: rv1, agent_ids[1]: rv2}
        return cls(
            threshold=threshold,
            mode="simple",
            valuation_mode="fixed",
            valuations=vals,
        )

    def get_metadata(self) -> dict:
        return {
            **super().get_metadata(),
            "mode": self._mode,
            "threshold": self._threshold,
            "endowment": self._endowment,
            "valuation_range": list(self._valuation_range),
            "allow_commitment_updates": self._allow_updates,
            "valuation_mode": self._valuation_mode,
            "valuations": self._fixed_valuations,
            "turn_order": self._turn_order.value,
        }

    def spec(self) -> GameSpec:
        if self._mode == "simple":
            return self._spec_simple()
        return self._spec_full()

    def _spec_simple(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="Provision Point (Simple)",
            min_agents=2,
            description=(
                "All agents are equal contributors. Each decides how much to commit. "
                f"If total commitments >= threshold ({self._threshold}), the project is funded "
                "and each contributor receives their reservation value. "
                "If not funded, each contributor loses their commitment."
            ),
            phases=[
                Phase(
                    name="commit",
                    turn_order=self._turn_order,
                    allowed_action_types=["submit_commitment", "pass", "message_only"],
                    max_rounds=self._max_rounds_commit,
                ),
            ],
            action_types=[
                ActionTypeDef(
                    name="submit_commitment",
                    description="Submit a binding commitment amount",
                    payload_schema={"amount": {"type": "number", "minimum": 0}},
                ),
                ActionTypeDef(
                    name="pass",
                    description="Pass your turn without acting",
                    payload_schema={},
                ),
                ActionTypeDef(
                    name="message_only",
                    description="Send messages without advancing the turn",
                    payload_schema={},
                ),
            ],
            outcome_rule=OutcomeRule.ENGINE,
            initial_game_state={
                "commitments": {},
                "funded": None,
                "action_history": [],
                "resolved": False,
            },
        )

    def _spec_full(self) -> GameSpec:
        return GameSpec(
            game_id=GAME_ID,
            name="Provision Point (Collective Resource Pooling)",
            min_agents=2,
            description=(
                "A COORDINATOR proposes a collective project. CONTRIBUTORS each decide "
                "how much to commit. If total commitments >= threshold, the project is "
                "funded and contributors receive (valuation - commitment). Otherwise all "
                "commitments are refunded. Phases: announce → signal → commit."
            ),
            phases=[
                Phase(
                    name="announce",
                    turn_order=self._turn_order,
                    allowed_action_types=["announce_project", "message_only"],
                    max_rounds=self._max_rounds_announce,
                ),
                Phase(
                    name="signal",
                    turn_order=self._turn_order,
                    allowed_action_types=[
                        "signal_intent", "pass", "message_only",
                    ],
                    max_rounds=self._max_rounds_signal,
                ),
                Phase(
                    name="commit",
                    turn_order=self._turn_order,
                    allowed_action_types=[
                        "submit_commitment", "update_commitment",
                        "withdraw_commitment",
                        "pass", "message_only",
                    ],
                    max_rounds=self._max_rounds_commit,
                ),
            ],
            action_types=[
                ActionTypeDef(
                    name="announce_project",
                    description="Coordinator announces the project: description, threshold, and what contributors receive",
                    payload_schema={
                        "description": {"type": "string"},
                        "threshold": {"type": "number", "minimum": 0},
                        "return_description": {"type": "string"},
                    },
                ),
                ActionTypeDef(
                    name="signal_intent",
                    description="Non-binding signal of how much you intend to commit (cheap talk). In auto valuation mode, include optional my_valuation to privately set your valuation.",
                    payload_schema={
                        "approximate_amount": {"type": "number", "minimum": 0},
                        "my_valuation": {"type": "number", "minimum": 0, "optional": True},
                    },
                ),
                ActionTypeDef(
                    name="submit_commitment",
                    description="Submit a binding commitment (amount <= endowment). In auto valuation mode, include optional my_valuation to privately set your valuation.",
                    payload_schema={
                        "amount": {"type": "number", "minimum": 0},
                        "my_valuation": {"type": "number", "minimum": 0, "optional": True},
                    },
                ),
                ActionTypeDef(
                    name="update_commitment",
                    description="Revise your existing commitment",
                    payload_schema={"new_amount": {"type": "number", "minimum": 0}},
                ),
                ActionTypeDef(
                    name="withdraw_commitment",
                    description="Withdraw your commitment entirely",
                    payload_schema={},
                ),
                ActionTypeDef(
                    name="pass",
                    description="Pass your turn without acting",
                    payload_schema={},
                ),
                ActionTypeDef(
                    name="message_only",
                    description="Send messages without advancing the turn",
                    payload_schema={},
                ),
            ],
            outcome_rule=OutcomeRule.ENGINE,
            initial_game_state={
                "project_spec": None,
                "signals": {},
                "commitments": {},
                "funded": None,
                "action_history": [],
                "resolved": False,
            },
        )

    # ------------------------------------------------------------------
    # Private valuations
    # ------------------------------------------------------------------

    def _ensure_valuations(self, match: Match) -> None:
        if match.game_state.get("valuations") is not None:
            return
        if self._valuation_mode == "fixed":
            match.game_state["valuations"] = dict(self._fixed_valuations)  # type: ignore[arg-type]
        elif self._valuation_mode == "auto":
            match.game_state["valuations"] = {}  # contributors fill via my_valuation field
        else:  # random
            low, high = self._valuation_range
            rng = random.Random(f"{match.match_id}")
            vals = {}
            for i, aid in enumerate(match.agent_ids):
                if self._mode == "full" and i == _COORDINATOR:
                    continue
                vals[aid] = round(rng.uniform(low, high), 2)
            match.game_state["valuations"] = vals

    # ------------------------------------------------------------------
    # Phase / turn management
    # ------------------------------------------------------------------

    def _current_phase_name(self, match: Match) -> str:
        phases = match.spec.phases
        if not phases or match.current_phase_index >= len(phases):
            return ""
        return phases[match.current_phase_index].name

    def _advance_phase(self, match: Match, target_phase: str) -> None:
        for i, ph in enumerate(match.spec.phases):
            if ph.name == target_phase:
                match.current_phase_index = i
                match.current_round = 0
                break
        if target_phase == "announce":
            match.current_turn_index = _COORDINATOR
        else:
            match.current_turn_index = 1  # first contributor

    def _advance_contributor_turn(self, match: Match) -> None:
        """Advance turn among all agents (coordinator included so they can message)."""
        n = len(match.agent_ids)
        if n <= 1:
            return

        phase = match.spec.phases[match.current_phase_index]

        # Simple mode: check if all agents have committed → resolve
        if self._mode == "simple" and phase.name == "commit":
            commitments = match.game_state.get("commitments", {})
            if len(commitments) == n:
                total = sum(commitments.values())
                trigger = "threshold_met" if total >= self._threshold else "all_committed_below_threshold"
                self._resolve(match, trigger=trigger)
                return
            # Also check threshold met early
            total = sum(commitments.values())
            if total >= self._threshold:
                self._resolve(match, trigger="threshold_met")
                return
        elif self._mode == "full" and phase.name == "commit":
            # Full mode: early resolution on threshold met
            commitments = match.game_state.get("commitments", {})
            total = sum(commitments.values())
            project_spec = match.game_state.get("project_spec") or {}
            threshold = project_spec.get("threshold", self._threshold)
            if total >= threshold:
                self._resolve(match, trigger="threshold_met")
                return

        idx = match.current_turn_index + 1
        if idx >= n:
            idx = 0
            match.current_round += 1
        match.current_turn_index = idx
        # Check round limit → auto-advance or resolve
        if phase.max_rounds is not None and match.current_round >= phase.max_rounds:
            if phase.name == "signal":
                self._advance_phase(match, "commit")
            elif phase.name == "commit":
                self._resolve(match, trigger="rounds_exhausted")

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _resolve(self, match: Match, *, trigger: str = "unknown") -> None:
        self._ensure_valuations(match)
        commitments = match.game_state.get("commitments", {})
        threshold = self._threshold
        if self._mode == "full":
            project_spec = match.game_state.get("project_spec") or {}
            threshold = project_spec.get("threshold", self._threshold)
        total = sum(commitments.values())
        funded = total >= threshold
        match.game_state["funded"] = funded
        valuations = match.game_state.get("valuations", {})

        if self._mode == "simple":
            payoffs = self._resolve_simple_payoffs(match, funded, commitments, valuations)
        else:
            payoffs = self._resolve_full_payoffs(match, funded, commitments, valuations)

        match.outcome = {
            "payoffs": payoffs,
            "trigger": trigger,
            "total_committed": total,
            "threshold": threshold,
        }
        match.game_state["resolved"] = True
        match.status = MatchStatus.FINISHED

    def _resolve_full_payoffs(
        self, match: Match, funded: bool, commitments: dict, valuations: dict
    ) -> list[dict]:
        if funded:
            payoffs = []
            for i, aid in enumerate(match.agent_ids):
                if i == _COORDINATOR:
                    payoffs.append({"agent_id": aid, "utility": 0.0})
                elif aid in commitments and commitments[aid] > 0:
                    payoffs.append({"agent_id": aid, "utility": round(valuations.get(aid, 0) - commitments[aid], 2)})
                else:
                    payoffs.append({"agent_id": aid, "utility": 0.0})
            return payoffs
        return [{"agent_id": aid, "utility": 0.0} for aid in match.agent_ids]

    def _resolve_simple_payoffs(
        self, match: Match, funded: bool, commitments: dict, valuations: dict
    ) -> list[dict]:
        payoffs = []
        for aid in match.agent_ids:
            commitment = commitments.get(aid, 0)
            if funded:
                payoffs.append({"agent_id": aid, "utility": round(valuations.get(aid, 0) - commitment, 2), "commitment": commitment})
            else:
                payoffs.append({"agent_id": aid, "utility": 0.0, "commitment": commitment})
        return payoffs

    # ------------------------------------------------------------------
    # compute_turn_state
    # ------------------------------------------------------------------

    def compute_turn_state(self, match: Match, agent_id: str) -> TurnState | None:
        if match.game_id != GAME_ID:
            return None
        if match.status != MatchStatus.RUNNING:
            return self._not_running_turn_state(match, agent_id)

        self._ensure_valuations(match)
        phase_name = self._current_phase_name(match)
        n = len(match.agent_ids)
        idx = match.current_turn_index
        if idx < 0 or idx >= n:
            idx = 0
        current_turn_agent_id = match.agent_ids[idx]
        is_my_turn = current_turn_agent_id == agent_id
        messages = messages_visible_to(match.messages, agent_id)
        allowed_actions = build_allowed_actions(match.spec, phase_name, is_my_turn)

        if self._mode == "simple":
            allowed_actions = self._filter_actions_simple(allowed_actions, agent_id, match)
        else:
            agent_index = match.agent_ids.index(agent_id) if agent_id in match.agent_ids else -1
            allowed_actions = self._filter_actions_for_role(allowed_actions, agent_index, phase_name, match)

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

    def _filter_actions_simple(self, actions: list, agent_id: str, match: Match) -> list:
        """In simple mode: if already committed, only allow pass/message_only."""
        g = match.game_state
        has_commitment = agent_id in g.get("commitments", {})
        if has_commitment:
            return [a for a in actions if a.action_type in ("pass", "message_only")]
        return actions

    def _filter_actions_for_role(
        self, actions: list, agent_index: int, phase: str, match: Match
    ) -> list:
        g = match.game_state
        agent_id = match.agent_ids[agent_index] if 0 <= agent_index < len(match.agent_ids) else None

        if agent_index == _COORDINATOR:
            return [a for a in actions if a.action_type in ("announce_project", "pass", "message_only")]

        # Contributor — build allowed set based on phase
        if phase == "signal":
            allowed = {"signal_intent", "pass", "message_only"}
        elif phase == "commit":
            has_commitment = agent_id in g.get("commitments", {}) if agent_id else False
            if has_commitment:
                allowed = {"update_commitment", "withdraw_commitment", "pass", "message_only"}
                if not self._allow_updates:
                    allowed.discard("update_commitment")
            else:
                allowed = {"submit_commitment", "pass", "message_only"}
        else:
            allowed = {"message_only"}

        return [a for a in actions if a.action_type in allowed]

    def _visible_game_state(self, match: Match, agent_id: str) -> dict:
        if self._mode == "simple":
            return self._visible_game_state_simple(match, agent_id)

        g = match.game_state
        coordinator_id = match.agent_ids[0] if match.agent_ids else None
        contributor_ids = match.agent_ids[1:] if len(match.agent_ids) > 1 else []
        state: dict = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
            "coordinator": coordinator_id,
            "contributors": contributor_ids,
            "my_role": "coordinator" if agent_id == coordinator_id else "contributor",
            "project_spec": g.get("project_spec"),
            "signals": g.get("signals", {}),
            "commitments": g.get("commitments", {}),
            "total_committed": sum(g.get("commitments", {}).values()),
            "threshold": (g.get("project_spec") or {}).get("threshold", self._threshold),
            "endowment": self._endowment,
            "funded": g.get("funded"),
            "action_history": g.get("action_history", []),
            "valuation_mode": self._valuation_mode,
        }
        valuations = g.get("valuations", {})
        if agent_id in valuations:
            state["my_valuation"] = valuations[agent_id]
        return state

    def _visible_game_state_simple(self, match: Match, agent_id: str) -> dict:
        g = match.game_state
        all_commitments = g.get("commitments", {})
        state: dict = {
            "num_agents": len(match.agent_ids),
            "agent_ids": list(match.agent_ids),
            "my_role": "contributor",
            "my_commitment": all_commitments.get(agent_id),
            "num_committed": len(all_commitments),
            "threshold": self._threshold,
            "funded": g.get("funded"),
        }
        valuations = g.get("valuations", {})
        if agent_id in valuations:
            state["my_reservation_value"] = valuations[agent_id]
        return state

    # ------------------------------------------------------------------
    # apply_action
    # ------------------------------------------------------------------

    def apply_action(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        err = self._check_apply_preconditions(match, agent_id, GAME_ID)
        if err is not None:
            return err

        if self._mode == "simple":
            return self._apply_action_simple(match, agent_id, action)

        phase_name = self._current_phase_name(match)
        current_turn_agent_id = match.agent_ids[match.current_turn_index]
        agent_index = match.agent_ids.index(agent_id) if agent_id in match.agent_ids else -1
        at = action.action_type

        if at != "message_only" and agent_id != current_turn_agent_id:
            return action_error(ActionError.NOT_YOUR_TURN, f"It is {current_turn_agent_id}'s turn")

        if at == "announce_project":
            return self._do_announce(match, agent_id, agent_index, phase_name, action)
        if at == "signal_intent":
            return self._do_signal(match, agent_id, agent_index, phase_name, action)
        if at == "submit_commitment":
            return self._do_submit(match, agent_id, agent_index, phase_name, action)
        if at == "update_commitment":
            return self._do_update(match, agent_id, agent_index, phase_name, action)
        if at == "withdraw_commitment":
            return self._do_withdraw(match, agent_id, agent_index, phase_name)
        if at == "pass":
            return self._do_pass(match, agent_id, phase_name)
        if at == "message_only":
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "message_only", "phase": phase_name}
            )
            return action_ok()

        return action_error(ActionError.INVALID_ACTION_TYPE, f"Unknown action type: {at}")

    def _apply_action_simple(self, match: Match, agent_id: str, action: Action) -> ActionResult:
        """Handle actions in simple mode (no coordinator, single commit phase)."""
        self._ensure_valuations(match)
        phase_name = self._current_phase_name(match)
        n = len(match.agent_ids)
        idx = match.current_turn_index
        if idx < 0 or idx >= n:
            idx = 0
        current_turn_agent_id = match.agent_ids[idx]
        at = action.action_type

        if at != "message_only" and agent_id != current_turn_agent_id:
            return action_error(ActionError.NOT_YOUR_TURN, f"It is {current_turn_agent_id}'s turn")

        if at not in ("submit_commitment", "pass", "message_only"):
            return action_error(ActionError.INVALID_ACTION_TYPE, f"{at} not allowed in simple mode")

        if at == "message_only":
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "message_only", "phase": phase_name}
            )
            return action_ok()

        if at == "pass":
            match.game_state.setdefault("action_history", []).append(
                {"agent_id": agent_id, "action": "pass", "phase": phase_name}
            )
            self._advance_contributor_turn(match)
            return action_ok()

        # submit_commitment
        if agent_id in match.game_state.get("commitments", {}):
            return action_error(ActionError.GAME_RULE_VIOLATION, "Already committed")

        amount = action.payload.get("amount")
        if amount is None:
            return action_error(ActionError.INVALID_PAYLOAD, "amount is required")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return action_error(ActionError.INVALID_PAYLOAD, "amount must be a number")
        if amount < 0:
            return action_error(ActionError.INVALID_PAYLOAD, "amount must be >= 0")

        match.game_state["commitments"][agent_id] = amount
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "submit_commitment", "amount": amount, "phase": phase_name}
        )
        self._advance_contributor_turn(match)
        return action_ok()

    # --- Action handlers ---

    def _do_announce(
        self, match: Match, agent_id: str, agent_index: int, phase: str, action: Action
    ) -> ActionResult:
        if phase != "announce":
            return action_error(ActionError.GAME_RULE_VIOLATION, "announce_project only in announce phase")
        if agent_index != _COORDINATOR:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Only the coordinator can announce a project")
        if match.game_state.get("project_spec") is not None:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Project already announced")

        description = action.payload.get("description")
        threshold = action.payload.get("threshold")
        return_desc = action.payload.get("return_description")
        if not description:
            return action_error(ActionError.INVALID_PAYLOAD, "description is required")
        if threshold is None:
            return action_error(ActionError.INVALID_PAYLOAD, "threshold is required")
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return action_error(ActionError.INVALID_PAYLOAD, "threshold must be a number")
        if threshold < 0:
            return action_error(ActionError.INVALID_PAYLOAD, "threshold must be >= 0")
        if not return_desc:
            return action_error(ActionError.INVALID_PAYLOAD, "return_description is required")

        match.game_state["project_spec"] = {
            "description": description,
            "threshold": threshold,
            "return_description": return_desc,
        }
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "announce_project", "phase": phase}
        )
        self._advance_phase(match, "signal")
        return action_ok()

    def _do_signal(
        self, match: Match, agent_id: str, agent_index: int, phase: str, action: Action
    ) -> ActionResult:
        if phase != "signal":
            return action_error(ActionError.GAME_RULE_VIOLATION, "signal_intent only in signal phase")
        if agent_index == _COORDINATOR:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Coordinator cannot signal intent")

        amount = action.payload.get("approximate_amount") or action.payload.get("amount")
        if amount is None:
            return action_error(ActionError.INVALID_PAYLOAD, "approximate_amount is required")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return action_error(ActionError.INVALID_PAYLOAD, "approximate_amount must be a number")
        if amount < 0:
            return action_error(ActionError.INVALID_PAYLOAD, "approximate_amount must be >= 0")

        match.game_state["signals"][agent_id] = amount
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "signal_intent", "approximate_amount": amount, "phase": phase}
        )
        # In auto mode, silently store private valuation if provided
        self._extract_private_valuation(match, agent_id, action)
        self._advance_contributor_turn(match)
        return action_ok()

    def _extract_private_valuation(
        self, match: Match, agent_id: str, action: Action
    ) -> None:
        """Silently store my_valuation from payload (auto mode only). No action_history entry."""
        if self._valuation_mode != "auto":
            return
        val = action.payload.get("my_valuation")
        if val is None:
            return
        try:
            val = float(val)
        except (TypeError, ValueError):
            return
        if val >= 0:
            match.game_state.setdefault("valuations", {})[agent_id] = val

    def _do_submit(
        self, match: Match, agent_id: str, agent_index: int, phase: str, action: Action
    ) -> ActionResult:
        if phase != "commit":
            return action_error(ActionError.GAME_RULE_VIOLATION, "submit_commitment only in commit phase")
        if agent_index == _COORDINATOR:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Coordinator cannot commit")
        if agent_id in match.game_state.get("commitments", {}):
            return action_error(ActionError.GAME_RULE_VIOLATION, "Already committed — use update_commitment to revise")

        amount = action.payload.get("amount")
        if amount is None:
            return action_error(ActionError.INVALID_PAYLOAD, "amount is required")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return action_error(ActionError.INVALID_PAYLOAD, "amount must be a number")
        if amount < 0:
            return action_error(ActionError.INVALID_PAYLOAD, "amount must be >= 0")
        if amount > self._endowment:
            return action_error(ActionError.GAME_RULE_VIOLATION, f"amount {amount} exceeds endowment {self._endowment}")

        match.game_state["commitments"][agent_id] = amount
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "submit_commitment", "amount": amount, "phase": phase}
        )
        # In auto mode, silently store private valuation if provided
        self._extract_private_valuation(match, agent_id, action)
        self._advance_contributor_turn(match)
        return action_ok()

    def _do_update(
        self, match: Match, agent_id: str, agent_index: int, phase: str, action: Action
    ) -> ActionResult:
        if phase != "commit":
            return action_error(ActionError.GAME_RULE_VIOLATION, "update_commitment only in commit phase")
        if agent_index == _COORDINATOR:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Coordinator cannot update commitments")
        if not self._allow_updates:
            return action_error(ActionError.GAME_RULE_VIOLATION, "Commitment updates are disabled")
        if agent_id not in match.game_state.get("commitments", {}):
            return action_error(ActionError.GAME_RULE_VIOLATION, "No commitment to update — use submit_commitment first")

        new_amount = action.payload.get("new_amount") or action.payload.get("amount")
        if new_amount is None:
            return action_error(ActionError.INVALID_PAYLOAD, "new_amount is required")
        try:
            new_amount = float(new_amount)
        except (TypeError, ValueError):
            return action_error(ActionError.INVALID_PAYLOAD, "new_amount must be a number")
        if new_amount < 0:
            return action_error(ActionError.INVALID_PAYLOAD, "new_amount must be >= 0")
        if new_amount > self._endowment:
            return action_error(ActionError.GAME_RULE_VIOLATION, f"new_amount {new_amount} exceeds endowment {self._endowment}")

        match.game_state["commitments"][agent_id] = new_amount
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "update_commitment", "new_amount": new_amount, "phase": phase}
        )
        self._advance_contributor_turn(match)
        return action_ok()

    def _do_withdraw(
        self, match: Match, agent_id: str, _agent_index: int, phase: str
    ) -> ActionResult:
        if phase != "commit":
            return action_error(ActionError.GAME_RULE_VIOLATION, "withdraw_commitment only in commit phase")
        if agent_id not in match.game_state.get("commitments", {}):
            return action_error(ActionError.GAME_RULE_VIOLATION, "No commitment to withdraw")

        del match.game_state["commitments"][agent_id]
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "withdraw_commitment", "phase": phase}
        )
        self._advance_contributor_turn(match)
        return action_ok()

    def _do_pass(self, match: Match, agent_id: str, phase: str) -> ActionResult:
        if phase not in ("signal", "commit"):
            return action_error(ActionError.GAME_RULE_VIOLATION, "pass only in signal or commit phase")
        match.game_state.setdefault("action_history", []).append(
            {"agent_id": agent_id, "action": "pass", "phase": phase}
        )
        self._advance_contributor_turn(match)
        return action_ok()

    def compute_outcome(self, match: Match) -> dict | None:
        if match.status == MatchStatus.FINISHED and match.outcome is not None:
            return match.outcome
        return None
