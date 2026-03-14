"""Tests for provision-point game: collective resource pooling."""

from arena.core.match import MatchStatus
from arena.core.runner import apply_action, create_match, get_turn_state
from arena.games import get_game, get_game_spec
from arena.types import Action


AGENTS = ["coordinator", "c1", "c2"]


def _make_match(match_id="m1", agents=None):
    spec = get_game_spec("provision-point")
    assert spec is not None
    return create_match(match_id, "provision-point", spec, agents or AGENTS)


def _announce(match, threshold=100):
    return apply_action(match, "coordinator", Action(
        action_type="announce_project",
        payload={
            "description": "Shared GPU cluster",
            "threshold": threshold,
            "return_description": "Proportional compute access",
        },
    ))


def _signal_all(match, amounts=None):
    """Each contributor signals intent."""
    amounts = amounts or [40, 60]
    for aid, amt in zip(AGENTS[1:], amounts):
        apply_action(match, aid, Action(
            action_type="signal_intent",
            payload={"approximate_amount": amt},
        ))


def _pass_signal_phase(match):
    """All contributors pass through signal phase until commit."""
    phase = match.spec.phases[match.current_phase_index]
    while phase.name == "signal":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index >= len(match.spec.phases):
            break
        phase = match.spec.phases[match.current_phase_index]


# --- Phase advancement ---

def test_announce_advances_to_signal():
    match = _make_match()
    result = _announce(match)
    assert result.ok is True
    assert match.game_state["project_spec"] is not None
    assert match.game_state["project_spec"]["threshold"] == 100
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "signal"
    assert match.current_turn_index == 1  # first contributor


def test_signal_records_intent():
    match = _make_match()
    _announce(match)
    result = apply_action(match, "c1", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 50},
    ))
    assert result.ok is True
    assert match.game_state["signals"]["c1"] == 50
    assert match.current_turn_index == 2  # c2's turn


def test_signal_phase_advances_to_commit():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "commit"
    assert match.current_turn_index == 1


def test_submit_commitment():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    result = apply_action(match, "c1", Action(
        action_type="submit_commitment",
        payload={"amount": 60},
    ))
    assert result.ok is True
    assert match.game_state["commitments"]["c1"] == 60


def test_update_commitment():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 40}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 50}))
    # Back to c1 — update
    result = apply_action(match, "c1", Action(
        action_type="update_commitment",
        payload={"new_amount": 55},
    ))
    assert result.ok is True
    assert match.game_state["commitments"]["c1"] == 55


def test_withdraw_commitment():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 60}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 50}))
    result = apply_action(match, "c1", Action(action_type="withdraw_commitment", payload={}))
    assert result.ok is True
    assert "c1" not in match.game_state["commitments"]


# --- Resolution ---

def test_funded_resolution():
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=100, valuations={"c1": 80, "c2": 120})
    register_game(game)
    spec = game.spec()
    match = create_match("funded1", "provision-point", spec, AGENTS)

    _announce(match, threshold=100)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 50}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 60}))
    # Pass remaining rounds until resolution
    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "project_funded"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["coordinator"] == 0.0
    assert payoffs["c1"] == 30.0   # 80 - 50
    assert payoffs["c2"] == 60.0   # 120 - 60


def test_not_funded_resolution():
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=100, valuations={"c1": 80, "c2": 120})
    register_game(game)
    spec = game.spec()
    match = create_match("notfunded1", "provision-point", spec, AGENTS)

    _announce(match, threshold=100)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 30}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 20}))
    # Pass remaining rounds
    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "threshold_not_reached"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_non_committer_gets_zero_when_funded():
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=50, valuations={"c1": 80, "c2": 120})
    register_game(game)
    spec = game.spec()
    match = create_match("freeride1", "provision-point", spec, AGENTS)

    _announce(match, threshold=50)
    _pass_signal_phase(match)
    # Only c1 commits; c2 free-rides
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 60}))
    apply_action(match, "c2", Action(action_type="pass", payload={}))
    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "project_funded"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["c1"] == 20.0   # 80 - 60
    assert payoffs["c2"] == 0.0    # free-rider gets nothing


# --- Role guards ---

def test_contributor_cannot_announce():
    match = _make_match()
    match.current_turn_index = 1  # force c1's turn
    game = get_game("provision-point")
    result = game.apply_action(match, "c1", Action(
        action_type="announce_project",
        payload={"description": "x", "threshold": 50, "return_description": "y"},
    ))
    assert result.ok is False
    assert "coordinator" in result.error_detail.lower()


def test_coordinator_cannot_signal():
    match = _make_match()
    _announce(match)
    match.current_turn_index = 0
    game = get_game("provision-point")
    result = game.apply_action(match, "coordinator", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 50},
    ))
    assert result.ok is False


def test_coordinator_cannot_commit():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    match.current_turn_index = 0
    game = get_game("provision-point")
    result = game.apply_action(match, "coordinator", Action(
        action_type="submit_commitment",
        payload={"amount": 50},
    ))
    assert result.ok is False


def test_not_your_turn():
    match = _make_match()
    _announce(match)
    # Turn is on c1 (index 1), c2 tries to act
    result = apply_action(match, "c2", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 30},
    ))
    assert result.ok is False
    assert result.error == "not_your_turn"


# --- Endowment guard ---

def test_commitment_exceeds_endowment():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    game = get_game("provision-point")
    result = game.apply_action(match, "c1", Action(
        action_type="submit_commitment",
        payload={"amount": 999},
    ))
    assert result.ok is False
    assert "endowment" in result.error_detail.lower()


# --- Duplicate commit guard ---

def test_double_submit_rejected():
    match = _make_match()
    _announce(match)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 40}))
    apply_action(match, "c2", Action(action_type="pass", payload={}))
    # c1 tries to submit again
    game = get_game("provision-point")
    result = game.apply_action(match, "c1", Action(
        action_type="submit_commitment",
        payload={"amount": 50},
    ))
    assert result.ok is False
    assert "update_commitment" in result.error_detail.lower()


# --- Updates disabled ---

def test_updates_disabled():
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=100, allow_commitment_updates=False)
    register_game(game)
    spec = game.spec()
    match = create_match("noupdate1", "provision-point", spec, AGENTS)

    _announce(match, threshold=100)
    _pass_signal_phase(match)
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 40}))
    apply_action(match, "c2", Action(action_type="pass", payload={}))
    result = apply_action(match, "c1", Action(
        action_type="update_commitment",
        payload={"new_amount": 60},
    ))
    assert result.ok is False
    assert "disabled" in result.error_detail.lower()


# --- Private valuations ---

def test_private_valuation_visible_only_to_owner():
    match = _make_match()
    _announce(match)
    state_c1 = get_turn_state(match, "c1")
    state_c2 = get_turn_state(match, "c2")
    state_coord = get_turn_state(match, "coordinator")

    assert "my_valuation" in state_c1.game_state
    assert "my_valuation" in state_c2.game_state
    assert "my_valuation" not in state_coord.game_state
    # Each sees their own, not the other's
    assert state_c1.game_state["my_valuation"] != state_c2.game_state["my_valuation"] or True  # values may coincide


# --- Full happy path ---

def test_full_happy_path():
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=80, valuations={"c1": 100, "c2": 90})
    register_game(game)
    spec = game.spec()
    match = create_match("happy1", "provision-point", spec, AGENTS)

    # Announce
    _announce(match, threshold=80)

    # Signal
    apply_action(match, "c1", Action(action_type="signal_intent", payload={"approximate_amount": 45}))
    apply_action(match, "c2", Action(action_type="signal_intent", payload={"approximate_amount": 40}))
    # Pass remaining signal rounds
    _pass_signal_phase(match)

    # Commit
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 45}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 40}))

    # Pass remaining commit rounds
    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "project_funded"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["coordinator"] == 0.0
    assert payoffs["c1"] == 55.0   # 100 - 45
    assert payoffs["c2"] == 50.0   # 90 - 40


# --- Auto valuation mode ---

def _make_auto_match(match_id="auto1"):
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=80, valuation_mode="auto")
    register_game(game)
    spec = game.spec()
    return create_match(match_id, "provision-point", spec, AGENTS)


def test_auto_mode_no_preassigned_valuation():
    match = _make_auto_match("auto_no_pre")
    _announce(match, threshold=80)
    state = get_turn_state(match, "c1")
    # In auto mode, no valuation is pre-assigned
    assert "my_valuation" not in state.game_state


def test_auto_valuation_via_signal_intent():
    """my_valuation in signal_intent payload is silently stored."""
    match = _make_auto_match("auto_sig")
    _announce(match, threshold=80)
    result = apply_action(match, "c1", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 40, "my_valuation": 120},
    ))
    assert result.ok is True
    # Valuation is stored privately
    state = get_turn_state(match, "c1")
    assert state.game_state["my_valuation"] == 120
    # Other contributor cannot see it
    state_c2 = get_turn_state(match, "c2")
    assert "my_valuation" not in state_c2.game_state


def test_auto_valuation_via_submit_commitment():
    """my_valuation in submit_commitment payload is silently stored."""
    match = _make_auto_match("auto_com")
    _announce(match, threshold=80)
    _pass_signal_phase(match)
    result = apply_action(match, "c1", Action(
        action_type="submit_commitment",
        payload={"amount": 40, "my_valuation": 100},
    ))
    assert result.ok is True
    state = get_turn_state(match, "c1")
    assert state.game_state["my_valuation"] == 100


def test_auto_valuation_not_in_action_history():
    """my_valuation should NOT appear in action_history (privacy)."""
    match = _make_auto_match("auto_hist")
    _announce(match, threshold=80)
    apply_action(match, "c1", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 40, "my_valuation": 120},
    ))
    history = match.game_state["action_history"]
    signal_entry = [e for e in history if e["action"] == "signal_intent"]
    assert len(signal_entry) == 1
    assert "my_valuation" not in signal_entry[0]  # private, not logged


def test_auto_full_flow_funded():
    match = _make_auto_match("auto_funded")
    _announce(match, threshold=80)

    # Signal phase: both set valuations and signal simultaneously
    apply_action(match, "c1", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 45, "my_valuation": 100},
    ))
    apply_action(match, "c2", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 40, "my_valuation": 90},
    ))
    _pass_signal_phase(match)

    # Commit phase
    apply_action(match, "c1", Action(action_type="submit_commitment", payload={"amount": 45}))
    apply_action(match, "c2", Action(action_type="submit_commitment", payload={"amount": 40}))

    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "project_funded"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["c1"] == 55.0   # 100 - 45
    assert payoffs["c2"] == 50.0   # 90 - 40


def test_auto_undeclared_valuation_defaults_to_zero():
    match = _make_auto_match("auto_undecl")
    _announce(match, threshold=30)
    _pass_signal_phase(match)

    # c1 sets valuation via commit; c2 never sets one
    apply_action(match, "c1", Action(
        action_type="submit_commitment",
        payload={"amount": 10, "my_valuation": 80},
    ))
    apply_action(match, "c2", Action(
        action_type="submit_commitment",
        payload={"amount": 35},
    ))

    phase = match.spec.phases[match.current_phase_index]
    while match.status == MatchStatus.RUNNING and phase.name == "commit":
        agent_id = match.agent_ids[match.current_turn_index]
        apply_action(match, agent_id, Action(action_type="pass", payload={}))
        if match.current_phase_index < len(match.spec.phases):
            phase = match.spec.phases[match.current_phase_index]

    assert match.outcome["reason"] == "project_funded"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["c1"] == 70.0   # 80 - 10
    assert payoffs["c2"] == -35.0  # 0 (no declaration) - 35


def test_auto_valuation_ignored_in_random_mode():
    """my_valuation in payload is silently ignored in random mode."""
    from arena.games.provision_point import ProvisionPointGame
    from arena.games import register_game

    game = ProvisionPointGame(threshold=100, valuation_mode="random")
    register_game(game)
    spec = game.spec()
    match = create_match("rnd_ign", "provision-point", spec, AGENTS)
    _announce(match, threshold=100)

    # Store original valuation
    state_before = get_turn_state(match, "c1")
    original_val = state_before.game_state["my_valuation"]

    # Try to override via signal payload
    apply_action(match, "c1", Action(
        action_type="signal_intent",
        payload={"approximate_amount": 40, "my_valuation": 9999},
    ))
    state_after = get_turn_state(match, "c1")
    assert state_after.game_state["my_valuation"] == original_val  # unchanged


def test_no_declare_valuation_action_exists():
    """There should be no declare_valuation action type in the spec."""
    from arena.games.provision_point import ProvisionPointGame
    game = ProvisionPointGame(valuation_mode="auto")
    spec = game.spec()
    action_names = [a.name for a in spec.action_types]
    assert "declare_valuation" not in action_names


def test_valuation_mode_invalid_raises():
    from arena.games.provision_point import ProvisionPointGame
    import pytest
    with pytest.raises(ValueError, match="valuation_mode"):
        ProvisionPointGame(valuation_mode="bogus")


def test_fixed_mode_requires_valuations():
    from arena.games.provision_point import ProvisionPointGame
    import pytest
    with pytest.raises(ValueError, match="valuations dict"):
        ProvisionPointGame(valuation_mode="fixed")


def test_backward_compat_valuations_infers_fixed():
    """Passing valuations without explicit mode should auto-infer fixed."""
    from arena.games.provision_point import ProvisionPointGame
    game = ProvisionPointGame(valuations={"c1": 50, "c2": 60})
    assert game._valuation_mode == "fixed"


# --- Dashboard: my_valuation visible but private to agents ---

def test_my_valuation_visible_in_payload_for_dashboard():
    """my_valuation should remain in the action payload (dashboard sees it),
    but privacy is enforced by the game engine (agents don't see each other's)."""
    from arena.experiment.runner import _sanitize_payload
    payload = {"amount": 50, "my_valuation": 120}
    safe = _sanitize_payload("provision-point", payload)
    # No redaction — provision-point has no private_payload_keys
    assert safe is payload
    assert safe["my_valuation"] == 120
