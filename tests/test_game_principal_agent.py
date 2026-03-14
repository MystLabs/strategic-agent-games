"""Tests for principal-agent game: 3-agent task delegation with oracle verification."""

from arena.core.match import MatchStatus
from arena.core.runner import apply_action, create_match, get_turn_state
from arena.games import get_game, get_game_spec
from arena.types import Action


AGENTS = ["principal", "worker", "oracle"]


def _make_match(match_id="m1"):
    spec = get_game_spec("principal-agent")
    assert spec is not None
    return create_match(match_id, "principal-agent", spec, AGENTS)


def _post_contract(match, **overrides):
    payload = {
        "task_description": "Write unit tests",
        "success_criteria": "All tests pass with >80% coverage",
        **overrides,
    }
    return apply_action(match, "principal", Action(action_type="post_contract", payload=payload))


def _full_flow_to_verify(match):
    """Run through offer→clarify→execute to reach verify phase (accept from clarify)."""
    _post_contract(match)
    apply_action(match, "worker", Action(action_type="accept_contract", payload={}))
    apply_action(match, "worker", Action(action_type="submit_deliverable", payload={"content": "Here is my work"}))


# --- Phase advancement ---

def test_post_contract_advances_to_clarify():
    match = _make_match()
    result = _post_contract(match)
    assert result.ok is True
    assert match.game_state["contract"] is not None
    assert match.game_state["contract"]["task_description"] == "Write unit tests"
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "clarify"
    # Turn should be on worker (index 1) for clarify
    assert match.current_turn_index == 1


def test_ask_and_answer_clarification():
    match = _make_match()
    _post_contract(match)

    # Worker asks
    result = apply_action(match, "worker", Action(
        action_type="ask_clarification",
        payload={"question": "What framework?"},
    ))
    assert result.ok is True
    assert len(match.game_state["clarifications"]) == 1
    assert match.game_state["clarifications"][0]["question"] == "What framework?"
    assert match.game_state["clarifications"][0]["answer"] is None
    assert match.current_turn_index == 0  # principal's turn to answer

    # Principal answers
    result = apply_action(match, "principal", Action(
        action_type="answer_clarification",
        payload={"answer": "Use pytest"},
    ))
    assert result.ok is True
    assert match.game_state["clarifications"][0]["answer"] == "Use pytest"
    assert match.current_turn_index == 1  # back to worker


def test_skip_clarify_advances_to_respond():
    match = _make_match()
    _post_contract(match)

    # Worker skips clarify
    result = apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))
    assert result.ok is True
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "respond"
    assert match.current_turn_index == 1  # worker responds


def test_principal_can_skip_clarify():
    """Principal can also skip clarify phase."""
    match = _make_match()
    _post_contract(match)
    # Set turn to principal manually to test
    match.current_turn_index = 0
    result = apply_action(match, "principal", Action(action_type="skip_clarify", payload={}))
    assert result.ok is True
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "respond"


def test_accept_contract_advances_to_execute():
    match = _make_match()
    _post_contract(match)
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))

    result = apply_action(match, "worker", Action(action_type="accept_contract", payload={}))
    assert result.ok is True
    assert match.game_state["accepted"] is True
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "execute"


def test_accept_contract_from_clarify_phase():
    """Worker can accept directly from clarify phase, skipping respond."""
    match = _make_match()
    _post_contract(match)
    # Still in clarify phase, worker accepts directly
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "clarify"

    result = apply_action(match, "worker", Action(action_type="accept_contract", payload={}))
    assert result.ok is True
    assert match.game_state["accepted"] is True
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "execute"


def test_reject_contract_from_clarify_phase():
    """Worker can reject directly from clarify phase."""
    match = _make_match()
    _post_contract(match)

    result = apply_action(match, "worker", Action(
        action_type="reject_contract",
        payload={"reason": "Not interested"},
    ))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "contract_rejected"


def test_reject_contract_ends_game():
    match = _make_match()
    _post_contract(match)
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))

    result = apply_action(match, "worker", Action(
        action_type="reject_contract",
        payload={"reason": "Too vague"},
    ))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome is not None
    assert match.outcome["reason"] == "contract_rejected"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_submit_deliverable_advances_to_verify():
    match = _make_match()
    _post_contract(match)
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))
    apply_action(match, "worker", Action(action_type="accept_contract", payload={}))

    result = apply_action(match, "worker", Action(
        action_type="submit_deliverable",
        payload={"content": "Here is my deliverable"},
    ))
    assert result.ok is True
    assert match.game_state["deliverable"] == "Here is my deliverable"
    phase = match.spec.phases[match.current_phase_index]
    assert phase.name == "verify"
    assert match.current_turn_index == 2  # oracle


def test_record_outcome_score_success():
    match = _make_match()
    _full_flow_to_verify(match)

    result = apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 85, "notes": "Excellent work"},
    ))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.game_state["outcome_label"] == "success"
    assert match.game_state["payment"] == 10
    assert match.outcome["reason"] == "task_resolved_success"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["worker"] == 10
    assert payoffs["principal"] == -10
    assert payoffs["oracle"] == 0.0


def test_record_outcome_score_partial():
    match = _make_match()
    _full_flow_to_verify(match)

    result = apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 60, "notes": "Meets some criteria"},
    ))
    assert result.ok is True
    assert match.game_state["outcome_label"] == "partial"
    assert match.game_state["payment"] == 3
    assert match.outcome["reason"] == "task_resolved_partial"


def test_record_outcome_score_fail():
    match = _make_match()
    _full_flow_to_verify(match)

    result = apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 30, "notes": "Did not meet requirements"},
    ))
    assert result.ok is True
    assert match.game_state["outcome_label"] == "fail"
    assert match.game_state["payment"] == 0
    assert match.outcome["reason"] == "task_resolved_fail"


def test_full_happy_path():
    match = _make_match()

    # Offer
    _post_contract(match)

    # Clarify
    apply_action(match, "worker", Action(
        action_type="ask_clarification",
        payload={"question": "Which language?"},
    ))
    apply_action(match, "principal", Action(
        action_type="answer_clarification",
        payload={"answer": "Python"},
    ))
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))

    # Respond
    apply_action(match, "worker", Action(action_type="accept_contract", payload={}))

    # Execute
    apply_action(match, "worker", Action(
        action_type="submit_deliverable",
        payload={"content": "Tests written in Python with 95% coverage"},
    ))

    # Verify
    result = apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 90, "notes": "Exceeds criteria"},
    ))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "task_resolved_success"
    payoffs = {p["agent_id"]: p["utility"] for p in match.outcome["payoffs"]}
    assert payoffs["worker"] == 10
    assert payoffs["principal"] == -10
    assert payoffs["oracle"] == 0.0


# --- Role guards ---

def test_worker_cannot_post_contract():
    match = _make_match()
    # Worker tries to post (but it's principal's turn and wrong role)
    match.current_turn_index = 1  # force worker's turn
    game = get_game("principal-agent")
    result = game.apply_action(match, "worker", Action(
        action_type="post_contract",
        payload={"task_description": "hack", "success_criteria": "none"},
    ))
    assert result.ok is False
    assert "principal" in result.error_detail.lower()


def test_principal_cannot_submit_deliverable():
    match = _make_match()
    _post_contract(match)
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))
    apply_action(match, "worker", Action(action_type="accept_contract", payload={}))

    # Force principal's turn
    match.current_turn_index = 0
    game = get_game("principal-agent")
    result = game.apply_action(match, "principal", Action(
        action_type="submit_deliverable",
        payload={"content": "principal trying to deliver"},
    ))
    assert result.ok is False
    assert "worker" in result.error_detail.lower()


def test_oracle_only_acts_in_verify():
    match = _make_match()
    _post_contract(match)

    # Force oracle's turn in clarify phase
    match.current_turn_index = 2
    game = get_game("principal-agent")
    result = game.apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 50, "notes": "test"},
    ))
    assert result.ok is False


def test_not_your_turn_clarify():
    match = _make_match()
    _post_contract(match)
    # Turn is on worker (index 1), principal tries to ask clarification
    result = apply_action(match, "principal", Action(
        action_type="ask_clarification",
        payload={"question": "wrong agent"},
    ))
    assert result.ok is False
    assert result.error == "not_your_turn"


def test_custom_outcome_levels():
    from arena.games.principal_agent import PrincipalAgentGame
    from arena.games import register_game

    custom_levels = [
        {"label": "bad", "threshold": 0, "payment": 0},
        {"label": "ok", "threshold": 40, "payment": 5},
        {"label": "great", "threshold": 90, "payment": 20},
    ]
    game = PrincipalAgentGame(outcome_levels=custom_levels)
    register_game(game)
    spec = game.spec()
    match = create_match("m_custom", "principal-agent", spec, AGENTS)

    _post_contract(match)
    apply_action(match, "worker", Action(action_type="skip_clarify", payload={}))
    apply_action(match, "worker", Action(action_type="accept_contract", payload={}))
    apply_action(match, "worker", Action(action_type="submit_deliverable", payload={"content": "work"}))
    apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 45, "notes": "ok-ish"},
    ))

    assert match.game_state["outcome_label"] == "ok"
    assert match.game_state["payment"] == 5


def test_score_out_of_range_rejected():
    match = _make_match()
    _full_flow_to_verify(match)

    game = get_game("principal-agent")
    result = game.apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": 150, "notes": "too high"},
    ))
    assert result.ok is False
    assert result.error == "invalid_payload"

    result = game.apply_action(match, "oracle", Action(
        action_type="record_outcome_score",
        payload={"score": -5, "notes": "negative"},
    ))
    assert result.ok is False
    assert result.error == "invalid_payload"
