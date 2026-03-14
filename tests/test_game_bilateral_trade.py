"""Tests for bilateral trade game: request, negotiate, deliver, verify.

Covers both 2-agent (classic) and N-agent (competitive) modes.
"""

from arena.core.match import MatchStatus
from arena.core.runner import apply_action, create_match, get_turn_state
from arena.games import get_game, get_game_spec
from arena.games.bilateral_trade import BilateralTradeGame
from arena.types import Action


# ── helpers ──────────────────────────────────────────────────────────────────

def _setup():
    """Create a fresh bilateral-trade match with agents 'init' (initiator) and 'prov' (provider)."""
    spec = get_game_spec("bilateral-trade")
    assert spec is not None
    return create_match("bt1", "bilateral-trade", spec, ["init", "prov"])


def _post_request(match, description="write tests", max_budget=100):
    return apply_action(match, "init", Action(action_type="post_request", payload={"description": description, "max_budget": max_budget}))


def _propose(match, agent_id, scope="unit tests", price=50):
    return apply_action(match, agent_id, Action(action_type="propose", payload={"scope": scope, "price": price}))


def _accept_proposal(match, agent_id):
    return apply_action(match, agent_id, Action(action_type="accept_proposal", payload={}))


def _submit_deliverable(match, content="here are the tests"):
    return apply_action(match, "prov", Action(action_type="submit_deliverable", payload={"content": content}))


def _reach_verify_phase(match):
    """Drive match through request → negotiate → deliver, landing in verify."""
    _post_request(match)
    _propose(match, "init", price=50)
    _accept_proposal(match, "prov")
    _submit_deliverable(match)


# ── tests ────────────────────────────────────────────────────────────────────

def test_post_request_advances_to_negotiate():
    """post_request sets request state and moves to the negotiate phase."""
    match = _setup()
    result = _post_request(match, description="build API", max_budget=200)
    assert result.ok is True
    assert match.game_state["request"] == {"description": "build API", "max_budget": 200.0}
    assert match.spec.phases[match.current_phase_index].name == "negotiate"
    assert len(match.game_state["action_history"]) == 1


def test_propose_updates_proposal():
    """propose sets proposal with scope, price, proposed_by and advances turn."""
    match = _setup()
    _post_request(match)
    result = _propose(match, "init", scope="API endpoints", price=80)
    assert result.ok is True
    assert match.game_state["proposal"] == {"scope": "API endpoints", "price": 80.0, "proposed_by": "init"}
    # Turn advances to provider
    assert match.agent_ids[match.current_turn_index] == "prov"


def test_counter_propose():
    """Provider can counter-propose, overwriting the previous proposal."""
    match = _setup()
    _post_request(match)
    _propose(match, "init", scope="full API", price=80)
    result = _propose(match, "prov", scope="basic API", price=40)
    assert result.ok is True
    assert match.game_state["proposal"]["proposed_by"] == "prov"
    assert match.game_state["proposal"]["price"] == 40.0


def test_accept_proposal_advances_to_deliver():
    """accept_proposal copies proposal to agreement and moves to deliver phase."""
    match = _setup()
    _post_request(match)
    _propose(match, "init", scope="tests", price=60)
    result = _accept_proposal(match, "prov")
    assert result.ok is True
    assert match.game_state["agreement"] == {"scope": "tests", "price": 60.0, "proposed_by": "init"}
    assert match.spec.phases[match.current_phase_index].name == "deliver"


def test_cannot_accept_own_proposal():
    """Agent cannot accept their own proposal."""
    match = _setup()
    _post_request(match)
    _propose(match, "init", price=50)
    # Force turn back to init to test the guard
    match.current_turn_index = 0
    game = get_game("bilateral-trade")
    result = game.apply_action(match, "init", Action(action_type="accept_proposal", payload={}))
    assert result.ok is False
    assert result.error == "game_rule_violation"
    assert "Cannot accept your own proposal" in result.error_detail


def test_reject_and_exit():
    """reject_and_exit ends game with 0 payoffs for both agents."""
    match = _setup()
    _post_request(match)
    result = apply_action(match, "init", Action(action_type="reject_and_exit", payload={"reason": "too expensive"}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "negotiation_failed"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_price_exceeds_budget():
    """Proposing a price above max_budget is rejected."""
    match = _setup()
    _post_request(match, max_budget=100)
    game = get_game("bilateral-trade")
    result = game.apply_action(match, "init", Action(action_type="propose", payload={"scope": "x", "price": 150}))
    assert result.ok is False
    assert result.error == "game_rule_violation"
    assert "exceeds max_budget" in result.error_detail


def test_full_happy_path_trade_completed():
    """Full flow: request → propose → accept → deliver → accept_delivery."""
    match = _setup()
    _reach_verify_phase(match)
    result = apply_action(match, "init", Action(action_type="accept_delivery", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "trade_completed"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -50.0
    assert payoffs["prov"] == 50.0


def test_dispute_delivery_no_payment():
    """Dispute with default no_payment: both get 0."""
    match = _setup()
    _reach_verify_phase(match)
    result = apply_action(match, "init", Action(action_type="dispute_delivery", payload={"reason": "incomplete"}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "delivery_disputed_no_payment"
    assert match.game_state["delivery_accepted"] is False
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_dispute_delivery_split():
    """Dispute with split resolution: 50/50 of agreed price."""
    from arena.games.bilateral_trade import BilateralTradeGame

    game = BilateralTradeGame(dispute_resolution="split")
    spec = game.spec()
    match = create_match("bt-split", "bilateral-trade", spec, ["init", "prov"])
    # Drive to verify phase directly through game instance
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 80}))
    game.apply_action(match, "init", Action(action_type="propose", payload={"scope": "work", "price": 80}))
    game.apply_action(match, "prov", Action(action_type="accept_proposal", payload={}))
    game.apply_action(match, "prov", Action(action_type="submit_deliverable", payload={"content": "result"}))
    result = game.apply_action(match, "init", Action(action_type="dispute_delivery", payload={"reason": "bad"}))
    assert result.ok is True
    assert match.outcome["reason"] == "delivery_disputed_split"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -40.0  # -80 * 0.5
    assert payoffs["prov"] == 40.0   #  80 * 0.5


def test_provider_cannot_post_request():
    """Provider cannot post_request; only the initiator can."""
    match = _setup()
    game = get_game("bilateral-trade")
    result = game.apply_action(match, "prov", Action(action_type="post_request", payload={"description": "x", "max_budget": 10}))
    assert result.ok is False
    assert result.error == "not_your_turn"


def test_not_your_turn_negotiate():
    """Acting out of turn in negotiate phase returns NOT_YOUR_TURN."""
    match = _setup()
    _post_request(match)
    # It's init's turn (index 0); prov tries to act
    result = apply_action(match, "prov", Action(action_type="propose", payload={"scope": "x", "price": 10}))
    assert result.ok is False
    assert result.error == "not_your_turn"


def test_max_rounds_negotiate():
    """Exceeding max_rounds in negotiate phase ends game."""
    from arena.games.bilateral_trade import BilateralTradeGame

    game = BilateralTradeGame()
    spec = game.spec()
    match = create_match("bt-mr", "bilateral-trade", spec, ["init", "prov"])
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    # Override negotiate max_rounds to 1 for quick test
    match.spec.phases[1].max_rounds = 1
    game.apply_action(match, "init", Action(action_type="propose", payload={"scope": "a", "price": 50}))
    game.apply_action(match, "prov", Action(action_type="propose", payload={"scope": "b", "price": 30}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_action_history_full_flow():
    """action_history records all game actions across phases."""
    match = _setup()
    _reach_verify_phase(match)
    apply_action(match, "init", Action(action_type="accept_delivery", payload={}))
    history = match.game_state["action_history"]
    actions = [h["action"] for h in history]
    assert actions == ["post_request", "propose", "accept_proposal", "submit_deliverable", "accept_delivery"]


def test_turn_state_shows_correct_phase_and_allowed_actions():
    """get_turn_state returns correct phase and allowed actions for each agent."""
    match = _setup()
    ts_init = get_turn_state(match, "init")
    ts_prov = get_turn_state(match, "prov")
    assert ts_init.phase == "request"
    assert ts_init.is_my_turn is True
    assert ts_prov.is_my_turn is False
    # Initiator has post_request available
    action_types = [a.action_type for a in ts_init.allowed_actions]
    assert "post_request" in action_types


# ══════════════════════════════════════════════════════════════════════════════
# N-agent competitive mode tests (3+ agents)
# ══════════════════════════════════════════════════════════════════════════════

def _setup_multi(agent_ids=None):
    """Create a fresh bilateral-trade match with 3+ agents (competitive mode)."""
    if agent_ids is None:
        agent_ids = ["init", "prov1", "prov2"]
    spec = get_game_spec("bilateral-trade")
    assert spec is not None
    return create_match("bt-multi", "bilateral-trade", spec, agent_ids)


def _multi_post_request(match, description="build API", max_budget=100):
    return apply_action(match, "init", Action(action_type="post_request", payload={"description": description, "max_budget": max_budget}))


def _multi_propose(match, agent_id, scope="unit tests", price=50):
    return apply_action(match, agent_id, Action(action_type="propose", payload={"scope": scope, "price": price}))


def _multi_accept_proposal(match, provider_id):
    return apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": provider_id}))


def _multi_submit_deliverable(match, agent_id, content="here is the work"):
    return apply_action(match, agent_id, Action(action_type="submit_deliverable", payload={"content": content}))


def _multi_reach_verify(match, selected="prov1"):
    """Drive a 3-agent match through all phases to verify."""
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="full API", price=60)
    _multi_propose(match, "prov2", scope="basic API", price=40)
    _multi_accept_proposal(match, selected)
    _multi_submit_deliverable(match, selected, content="the deliverable")


# ── competitive mode tests ───────────────────────────────────────────────────

def test_multi_post_request_sets_active_providers():
    """post_request with 3+ agents populates active_providers."""
    match = _setup_multi()
    result = _multi_post_request(match, description="build API", max_budget=200)
    assert result.ok is True
    assert match.game_state["active_providers"] == ["prov1", "prov2"]
    assert match.spec.phases[match.current_phase_index].name == "negotiate"


def test_multi_provider_proposes_stored_in_proposals():
    """A provider's propose stores in proposals dict keyed by provider_id."""
    match = _setup_multi()
    _multi_post_request(match)
    result = _multi_propose(match, "prov1", scope="API endpoints", price=80)
    assert result.ok is True
    assert match.game_state["proposals"]["prov1"] == {"scope": "API endpoints", "price": 80.0}


def test_multi_multiple_providers_propose_independently():
    """Each provider's proposal is stored independently."""
    match = _setup_multi()
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="full solution", price=90)
    _multi_propose(match, "prov2", scope="minimal solution", price=30)
    proposals = match.game_state["proposals"]
    assert proposals["prov1"]["price"] == 90.0
    assert proposals["prov2"]["price"] == 30.0


def test_multi_provider_updates_proposal():
    """A provider can overwrite their own proposal by calling propose again."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    _multi_propose(match, "prov1", scope="v1", price=80)
    _multi_propose(match, "prov2", scope="v2", price=50)
    # Init has a turn now (proposals exist) — pass to cycle back to prov1
    game.apply_action(match, "init", Action(action_type="pass", payload={}))
    result = _multi_propose(match, "prov1", scope="v1-updated", price=60)
    assert result.ok is True
    assert match.game_state["proposals"]["prov1"] == {"scope": "v1-updated", "price": 60.0}


def test_multi_initiator_cannot_propose():
    """Initiator cannot call propose in competitive mode."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    # Providers propose so initiator gets a turn
    _multi_propose(match, "prov1", scope="work", price=50)
    _multi_propose(match, "prov2", scope="work2", price=40)
    # Now it's initiator's turn — propose should be rejected
    result = game.apply_action(match, "init", Action(action_type="propose", payload={"scope": "x", "price": 10}))
    assert result.ok is False
    assert result.error == "game_rule_violation"


def test_multi_provider_cannot_accept_proposal():
    """Provider cannot call accept_proposal — only initiator can."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    _multi_propose(match, "prov1", scope="work", price=50)
    # It's prov2's turn — provider cannot accept
    result = game.apply_action(match, "prov2", Action(action_type="accept_proposal", payload={"provider_id": "prov1"}))
    assert result.ok is False


def test_multi_accept_proposal_selects_provider():
    """accept_proposal sets agreement and selected_provider, advances to deliver."""
    match = _setup_multi()
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="full work", price=70)
    _multi_propose(match, "prov2", scope="basic work", price=40)
    result = _multi_accept_proposal(match, "prov2")
    assert result.ok is True
    assert match.game_state["agreement"] == {"provider_id": "prov2", "scope": "basic work", "price": 40.0}
    assert match.game_state["selected_provider"] == "prov2"
    assert match.spec.phases[match.current_phase_index].name == "deliver"


def test_multi_accept_nonexistent_provider_fails():
    """Accepting a proposal from a non-active provider fails."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    # Providers propose so initiator gets a turn
    _multi_propose(match, "prov1", scope="work", price=50)
    _multi_propose(match, "prov2", scope="work2", price=40)
    result = game.apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": "ghost"}))
    assert result.ok is False
    assert result.error == "game_rule_violation"


def test_multi_accept_provider_without_proposal_fails():
    """Accepting a provider who hasn't submitted a proposal fails."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    # prov1 proposes, prov2 passes — initiator gets turn with proposals present
    _multi_propose(match, "prov1", scope="work", price=50)
    game.apply_action(match, "prov2", Action(action_type="pass", payload={}))
    # Initiator tries to accept prov2 who never proposed
    result = game.apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": "prov2"}))
    assert result.ok is False
    assert result.error == "game_rule_violation"


def test_multi_reject_and_exit_provider():
    """Provider reject_and_exit removes them from active_providers."""
    match = _setup_multi()
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="work", price=50)
    # It's prov2's turn — they reject and exit
    result = apply_action(match, "prov2", Action(action_type="reject_and_exit", payload={"reason": "not interested"}))
    assert result.ok is True
    assert "prov2" not in match.game_state["active_providers"]
    assert match.status == MatchStatus.RUNNING


def test_multi_reject_and_exit_initiator_ends_game():
    """Initiator reject_and_exit ends the game immediately."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    # Providers propose so initiator gets a turn
    _multi_propose(match, "prov1", scope="work", price=50)
    _multi_propose(match, "prov2", scope="work2", price=40)
    result = game.apply_action(match, "init", Action(action_type="reject_and_exit", payload={"reason": "changed mind"}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "initiator_exited"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_multi_all_providers_exit_ends_game():
    """All providers exiting ends the game with 0 payoffs."""
    match = _setup_multi()
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    game.apply_action(match, "prov1", Action(action_type="reject_and_exit", payload={"reason": "bye"}))
    game.apply_action(match, "prov2", Action(action_type="reject_and_exit", payload={"reason": "bye"}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "all_providers_exited"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_multi_turn_skips_exited_providers():
    """After a provider exits, round-robin skips them."""
    match = _setup_multi(["init", "prov1", "prov2", "prov3"])
    _multi_post_request(match)
    game = get_game("bilateral-trade")
    game.apply_action(match, "prov1", Action(action_type="reject_and_exit", payload={"reason": "out"}))
    current = match.agent_ids[match.current_turn_index]
    assert current == "prov2"


def test_multi_full_happy_path_3_agents():
    """Full flow with 3 agents: payoffs correct."""
    match = _setup_multi()
    _multi_reach_verify(match, selected="prov1")
    result = apply_action(match, "init", Action(action_type="accept_delivery", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "trade_completed"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -60.0
    assert payoffs["prov1"] == 60.0
    assert payoffs["prov2"] == 0.0


def test_multi_full_happy_path_4_agents():
    """Full flow with 4 agents: payoffs correct for non-selected providers."""
    match = _setup_multi(["init", "prov1", "prov2", "prov3"])
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="premium", price=90)
    _multi_propose(match, "prov2", scope="standard", price=50)
    _multi_propose(match, "prov3", scope="budget", price=30)
    _multi_accept_proposal(match, "prov3")
    _multi_submit_deliverable(match, "prov3", content="budget deliverable")
    result = apply_action(match, "init", Action(action_type="accept_delivery", payload={}))
    assert result.ok is True
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -30.0
    assert payoffs["prov3"] == 30.0
    assert payoffs["prov1"] == 0.0
    assert payoffs["prov2"] == 0.0


def test_multi_dispute_delivery_no_payment():
    """Dispute with no_payment in competitive mode: all get 0."""
    match = _setup_multi()
    _multi_reach_verify(match, selected="prov1")
    result = apply_action(match, "init", Action(action_type="dispute_delivery", payload={"reason": "incomplete"}))
    assert result.ok is True
    assert match.outcome["reason"] == "delivery_disputed_no_payment"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_multi_dispute_delivery_split():
    """Dispute with split: 50/50 between initiator and selected provider, others 0."""
    game = BilateralTradeGame(dispute_resolution="split")
    spec = game.spec()
    match = create_match("bt-split-m", "bilateral-trade", spec, ["init", "prov1", "prov2"])
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    game.apply_action(match, "prov1", Action(action_type="propose", payload={"scope": "work", "price": 80}))
    game.apply_action(match, "prov2", Action(action_type="propose", payload={"scope": "work2", "price": 60}))
    game.apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": "prov1"}))
    game.apply_action(match, "prov1", Action(action_type="submit_deliverable", payload={"content": "result"}))
    result = game.apply_action(match, "init", Action(action_type="dispute_delivery", payload={"reason": "bad"}))
    assert result.ok is True
    assert match.outcome["reason"] == "delivery_disputed_split"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -40.0
    assert payoffs["prov1"] == 40.0
    assert payoffs["prov2"] == 0.0


def test_multi_price_exceeds_budget():
    """Proposing a price above max_budget is rejected in competitive mode."""
    match = _setup_multi()
    _multi_post_request(match, max_budget=100)
    game = get_game("bilateral-trade")
    result = game.apply_action(match, "prov1", Action(action_type="propose", payload={"scope": "x", "price": 150}))
    assert result.ok is False
    assert result.error == "game_rule_violation"
    assert "exceeds max_budget" in result.error_detail


def test_multi_max_rounds_exceeded():
    """Exceeding max_rounds in competitive negotiate phase ends game."""
    game = BilateralTradeGame()
    spec = game.spec()
    match = create_match("bt-mr-m", "bilateral-trade", spec, ["init", "prov1", "prov2"])
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    match.spec.phases[1].max_rounds = 1
    game.apply_action(match, "prov1", Action(action_type="propose", payload={"scope": "a", "price": 50}))
    game.apply_action(match, "prov2", Action(action_type="propose", payload={"scope": "b", "price": 40}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_multi_turn_state_shows_correct_info():
    """get_turn_state returns correct phase and competitive-mode state."""
    match = _setup_multi()
    ts_init = get_turn_state(match, "init")
    ts_prov = get_turn_state(match, "prov1")
    assert ts_init.phase == "request"
    assert ts_init.is_my_turn is True
    assert ts_prov.is_my_turn is False
    action_types = [a.action_type for a in ts_init.allowed_actions]
    assert "post_request" in action_types


def test_multi_sealed_bids_providers_only_see_own_proposal():
    """Providers see only their own proposal; initiator sees all (sealed bids)."""
    match = _setup_multi()
    _multi_post_request(match)
    _multi_propose(match, "prov1", scope="premium", price=90)
    _multi_propose(match, "prov2", scope="budget", price=30)
    # Initiator's turn state shows all proposals
    ts_init = get_turn_state(match, "init")
    assert "prov1" in ts_init.game_state["proposals"]
    assert "prov2" in ts_init.game_state["proposals"]
    # Provider 1 only sees their own proposal
    ts_prov1 = get_turn_state(match, "prov1")
    assert "prov1" in ts_prov1.game_state["proposals"]
    assert "prov2" not in ts_prov1.game_state["proposals"]
    # Provider 2 only sees their own proposal
    ts_prov2 = get_turn_state(match, "prov2")
    assert "prov2" in ts_prov2.game_state["proposals"]
    assert "prov1" not in ts_prov2.game_state["proposals"]


# ══════════════════════════════════════════════════════════════════════════════
# Free negotiate turn order tests
# ══════════════════════════════════════════════════════════════════════════════

def _setup_multi_random(agent_ids=None):
    """Create a competitive match with negotiate_turn_order='random'."""
    if agent_ids is None:
        agent_ids = ["init", "prov1", "prov2"]
    game = BilateralTradeGame(negotiate_turn_order="random")
    spec = game.spec()
    match = create_match("bt-random", "bilateral-trade", spec, agent_ids)
    return match, game


def test_multi_random_mode_any_provider_can_act():
    """In random mode, any active provider can act — not just the current_turn_index agent."""
    match, game = _setup_multi_random()
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    # After post_request, current_turn_index points to prov1 (index 1).
    # In random mode, prov2 should also be able to act.
    assert match.agent_ids[match.current_turn_index] == "prov1"
    result = game.apply_action(match, "prov2", Action(action_type="propose", payload={"scope": "work", "price": 40}))
    assert result.ok is True
    assert match.game_state["proposals"]["prov2"] == {"scope": "work", "price": 40.0}


def test_multi_random_mode_initiator_acts_after_one_proposal():
    """In random mode, initiator can act as soon as one proposal exists."""
    match, game = _setup_multi_random()
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    # Initiator cannot act before any proposal
    result = game.apply_action(match, "init", Action(action_type="pass", payload={}))
    assert result.ok is False
    assert result.error == "not_your_turn"
    # One provider proposes
    game.apply_action(match, "prov1", Action(action_type="propose", payload={"scope": "work", "price": 50}))
    # Now initiator can act (without waiting for prov2)
    result = game.apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": "prov1"}))
    assert result.ok is True
    assert match.game_state["selected_provider"] == "prov1"


def test_multi_random_mode_full_happy_path():
    """End-to-end 3-agent test in random mode."""
    match, game = _setup_multi_random()
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    # prov2 acts first (out of round-robin order)
    game.apply_action(match, "prov2", Action(action_type="propose", payload={"scope": "budget", "price": 30}))
    game.apply_action(match, "prov1", Action(action_type="propose", payload={"scope": "premium", "price": 80}))
    game.apply_action(match, "init", Action(action_type="accept_proposal", payload={"provider_id": "prov2"}))
    game.apply_action(match, "prov2", Action(action_type="submit_deliverable", payload={"content": "done"}))
    result = game.apply_action(match, "init", Action(action_type="accept_delivery", payload={}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "trade_completed"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["init"] == -30.0
    assert payoffs["prov2"] == 30.0
    assert payoffs["prov1"] == 0.0


def test_multi_random_mode_2_agent_both_can_act():
    """In 2-agent random mode, both agents can act regardless of current_turn_index."""
    game = BilateralTradeGame(negotiate_turn_order="random")
    spec = game.spec()
    match = create_match("bt-random-2", "bilateral-trade", spec, ["init", "prov"])
    game.apply_action(match, "init", Action(action_type="post_request", payload={"description": "task", "max_budget": 100}))
    # init proposes
    game.apply_action(match, "init", Action(action_type="propose", payload={"scope": "work", "price": 50}))
    # In random mode, both can act — use game.compute_turn_state directly (not the
    # runner's get_turn_state which uses the default registered game instance)
    ts_init = game.compute_turn_state(match, "init")
    ts_prov = game.compute_turn_state(match, "prov")
    assert ts_init.is_my_turn is True
    assert ts_prov.is_my_turn is True


def test_multi_initiator_skipped_until_proposals_exist():
    """Initiator is skipped in the round-robin until at least one proposal exists."""
    match = _setup_multi()
    _multi_post_request(match)
    # After post_request, negotiate starts at prov1 (index 1)
    assert match.agent_ids[match.current_turn_index] == "prov1"
    # Initiator should not have a turn yet
    ts_init = get_turn_state(match, "init")
    assert ts_init.is_my_turn is False
    # prov1 passes (no proposal yet) — turn goes to prov2, not init
    game = get_game("bilateral-trade")
    game.apply_action(match, "prov1", Action(action_type="pass", payload={}))
    assert match.agent_ids[match.current_turn_index] == "prov2"
    # prov2 proposes — now proposals exist, init should get next turn
    _multi_propose(match, "prov2", scope="work", price=50)
    assert match.agent_ids[match.current_turn_index] == "init"
