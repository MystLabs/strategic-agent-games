"""Tests for first-price sealed-bid auction game."""

from arena.core.match import MatchStatus
from arena.core.runner import apply_action, create_match, get_turn_state
from arena.games import get_game, get_game_spec
from arena.types import Action


def test_auction_submit_bid_stores_bid():
    """submit_bid stores the bid and does not reveal it to opponent."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    result = apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    assert result.ok is True
    assert match.game_state["bids"]["a"] == 40.0
    assert match.status == MatchStatus.RUNNING
    # Opponent cannot see bid amount
    ts_b = get_turn_state(match, "b")
    assert ts_b is not None
    assert ts_b.game_state["opponents_with_bid"] == ["a"]
    assert ts_b.game_state["num_bids_submitted"] == 1
    assert "my_bid" not in ts_b.game_state or ts_b.game_state["my_bid"] is None


def test_auction_both_bids_resolves():
    """When both bids are in, winner is determined and utilities computed."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    # Ensure valuations are set
    get_turn_state(match, "a")
    valuations = match.game_state["valuations"]
    apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 35}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome is not None
    assert match.outcome["winner"] == "a"
    assert match.outcome["reason"] == "auction_resolved"
    payoffs = {p["agent_id"]: p for p in match.outcome["payoffs"]}
    assert payoffs["a"]["utility"] == round(valuations["a"] - 40, 2)
    assert payoffs["a"]["bid"] == 40.0
    assert payoffs["b"]["utility"] == 0.0
    assert payoffs["b"]["bid"] == 35.0


def test_auction_tie_resolved():
    """Tied bids are broken deterministically by match_id seed."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("tie-test", "first-price-auction", spec, ["a", "b"])
    get_turn_state(match, "a")
    apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 50}))
    apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 50}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["winner"] in ("a", "b")
    # Run again with same match_id → same winner (deterministic)
    match2 = create_match("tie-test", "first-price-auction", spec, ["a", "b"])
    get_turn_state(match2, "a")
    apply_action(match2, "a", Action(action_type="submit_bid", payload={"bid": 50}))
    apply_action(match2, "b", Action(action_type="submit_bid", payload={"bid": 50}))
    assert match2.outcome["winner"] == match.outcome["winner"]


def test_auction_cannot_bid_twice():
    """Agent cannot submit a second bid."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    get_turn_state(match, "a")
    apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    # Force turn back to "a" to test the guard
    match.current_turn_index = 0
    game = get_game("first-price-auction")
    assert game is not None
    result = game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 45}))
    assert result.ok is False
    assert result.error == "game_rule_violation"


def test_auction_invalid_bid_rejected():
    """Negative bid is rejected."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    game = get_game("first-price-auction")
    assert game is not None
    result = game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": -5}))
    assert result.ok is False
    assert result.error == "invalid_payload"
    assert "bids" not in match.game_state or "a" not in match.game_state.get("bids", {})


def test_auction_max_rounds_no_bids():
    """If max_rounds exceeded without both bids, both get utility 0."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(max_rounds=1)
    spec = game.spec()
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    game._ensure_valuations(match)
    # a passes, b passes → round advances, hits max_rounds
    game.apply_action(match, "a", Action(action_type="pass", payload={}))
    game.apply_action(match, "b", Action(action_type="pass", payload={}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_auction_action_history_tracks_bids():
    """action_history records submit_bid without revealing the bid amount."""
    spec = get_game_spec("first-price-auction")
    assert spec is not None
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    get_turn_state(match, "a")
    apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    history = match.game_state["action_history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["agent_id"] == "a"
    assert entry["action"] == "submit_bid"
    assert "bid" not in entry  # bid amount is sealed


def test_auction_visible_state_hides_opponent_bid():
    """_visible_game_state shows own bid but hides opponent's bid amount."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80})
    spec = game.spec()
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    game._ensure_valuations(match)
    match.game_state["bids"]["a"] = 40.0
    visible_a = game._visible_game_state(match, "a")
    visible_b = game._visible_game_state(match, "b")
    # a can see own bid
    assert visible_a["my_bid"] == 40.0
    assert visible_a["my_valuation"] == 60
    # b cannot see a's bid amount, only that a has bid
    assert visible_b["my_bid"] is None
    assert visible_b["opponents_with_bid"] == ["a"]
    assert visible_b["num_bids_submitted"] == 1
    assert visible_b["my_valuation"] == 80


def test_auction_custom_valuations():
    """Fixed valuations are applied correctly."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80})
    spec = game.spec()
    match = create_match("m1", "first-price-auction", spec, ["a", "b"])
    game._ensure_valuations(match)
    assert match.game_state["valuations"] == {"a": 60, "b": 80}
    # Play through: a bids 40, b bids 35 → a wins
    game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    match.current_turn_index = 1  # ensure b's turn
    game.apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 35}))
    assert match.outcome["winner"] == "a"
    payoffs = {p["agent_id"]: p for p in match.outcome["payoffs"]}
    assert payoffs["a"]["utility"] == 20.0  # 60 - 40
    assert payoffs["b"]["utility"] == 0.0


# ── N-player tests ──────────────────────────────────────────────


def test_auction_three_players_highest_wins():
    """Three-player auction: highest bidder wins."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80, "c": 70})
    spec = game.spec()
    match = create_match("m3", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 30}))
    match.current_turn_index = 1
    game.apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 50}))
    match.current_turn_index = 2
    game.apply_action(match, "c", Action(action_type="submit_bid", payload={"bid": 40}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["winner"] == "b"
    payoffs = {p["agent_id"]: p for p in match.outcome["payoffs"]}
    assert payoffs["b"]["utility"] == 30.0  # 80 - 50
    assert payoffs["a"]["utility"] == 0.0
    assert payoffs["c"]["utility"] == 0.0


def test_auction_five_players_resolves():
    """Five-player auction resolves correctly."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    vals = {"a": 90, "b": 60, "c": 75, "d": 50, "e": 85}
    game = FirstPriceAuctionGame(valuations=vals)
    spec = game.spec()
    agents = ["a", "b", "c", "d", "e"]
    match = create_match("m5", "first-price-auction", spec, agents)
    game._ensure_valuations(match)
    bids = {"a": 70, "b": 30, "c": 60, "d": 25, "e": 65}
    for i, aid in enumerate(agents):
        match.current_turn_index = i
        game.apply_action(match, aid, Action(action_type="submit_bid", payload={"bid": bids[aid]}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["winner"] == "a"  # highest bid = 70
    payoffs = {p["agent_id"]: p for p in match.outcome["payoffs"]}
    assert payoffs["a"]["utility"] == 20.0  # 90 - 70
    for loser in ["b", "c", "d", "e"]:
        assert payoffs[loser]["utility"] == 0.0


def test_auction_n_player_visible_state():
    """N-player visible state shows correct opponent bid info."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80, "c": 70})
    spec = game.spec()
    match = create_match("m3v", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    # a bids
    match.game_state["bids"]["a"] = 30.0
    vis_b = game._visible_game_state(match, "b")
    assert vis_b["num_bidders"] == 3
    assert vis_b["opponents_with_bid"] == ["a"]
    assert vis_b["num_bids_submitted"] == 1
    assert vis_b["my_bid"] is None
    # c also bids
    match.game_state["bids"]["c"] = 40.0
    vis_b2 = game._visible_game_state(match, "b")
    assert sorted(vis_b2["opponents_with_bid"]) == ["a", "c"]
    assert vis_b2["num_bids_submitted"] == 2


def test_auction_n_player_tie():
    """Tie among 3 players is broken deterministically."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 60, "c": 60})
    spec = game.spec()
    match = create_match("tie3", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    for i, aid in enumerate(["a", "b", "c"]):
        match.current_turn_index = i
        game.apply_action(match, aid, Action(action_type="submit_bid", payload={"bid": 50}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["winner"] in ("a", "b", "c")
    # Deterministic: same result on replay
    match2 = create_match("tie3", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match2)
    for i, aid in enumerate(["a", "b", "c"]):
        match2.current_turn_index = i
        game.apply_action(match2, aid, Action(action_type="submit_bid", payload={"bid": 50}))
    assert match2.outcome["winner"] == match.outcome["winner"]


def test_auction_n_player_max_rounds():
    """N-player auction with max_rounds exceeded gives all players utility 0."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(max_rounds=1)
    spec = game.spec()
    match = create_match("mr3", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    # All pass → after 3 passes round wraps to 1, exceeds max_rounds=1
    game.apply_action(match, "a", Action(action_type="pass", payload={}))
    game.apply_action(match, "b", Action(action_type="pass", payload={}))
    game.apply_action(match, "c", Action(action_type="pass", payload={}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"
    assert len(match.outcome["payoffs"]) == 3
    for p in match.outcome["payoffs"]:
        assert p["utility"] == 0.0


def test_auction_n_player_partial_bids_max_rounds():
    """If only some agents bid before max_rounds, everyone gets 0."""
    from arena.games.first_price_auction import FirstPriceAuctionGame

    game = FirstPriceAuctionGame(max_rounds=2)
    spec = game.spec()
    match = create_match("partial3", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    # a bids, b and c keep passing until max rounds
    game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 40}))
    # b passes, c passes → round 1
    game.apply_action(match, "b", Action(action_type="pass", payload={}))
    game.apply_action(match, "c", Action(action_type="pass", payload={}))
    # a already bid so submit_bid removed; passes
    match.current_turn_index = 0
    game.apply_action(match, "a", Action(action_type="pass", payload={}))
    game.apply_action(match, "b", Action(action_type="pass", payload={}))
    game.apply_action(match, "c", Action(action_type="pass", payload={}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"


# ── RANDOM turn-order tests ──────────────────────────────────────


def test_auction_random_mode_any_agent_can_act():
    """In RANDOM mode, any agent can submit a bid regardless of turn index."""
    from arena.games.first_price_auction import FirstPriceAuctionGame
    from arena.spec import TurnOrder

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80, "c": 70}, turn_order=TurnOrder.RANDOM)
    spec = game.spec()
    match = create_match("random1", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    # c bids first (out of order) — should succeed in RANDOM mode
    result = game.apply_action(match, "c", Action(action_type="submit_bid", payload={"bid": 35}))
    assert result.ok is True
    assert match.game_state["bids"]["c"] == 35.0
    # b bids next
    result = game.apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 50}))
    assert result.ok is True
    # a bids last → resolves
    result = game.apply_action(match, "a", Action(action_type="submit_bid", payload={"bid": 30}))
    assert result.ok is True
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["winner"] == "b"


def test_auction_random_mode_is_my_turn_for_all():
    """In RANDOM mode, is_my_turn is True for all agents."""
    from arena.games.first_price_auction import FirstPriceAuctionGame
    from arena.spec import TurnOrder

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80}, turn_order=TurnOrder.RANDOM)
    spec = game.spec()
    match = create_match("random2", "first-price-auction", spec, ["a", "b"])
    game._ensure_valuations(match)
    ts_a = game.compute_turn_state(match, "a")
    ts_b = game.compute_turn_state(match, "b")
    assert ts_a.is_my_turn is True
    assert ts_b.is_my_turn is True
    # Both should have submit_bid in their allowed actions
    assert any(a.action_type == "submit_bid" for a in ts_a.allowed_actions)
    assert any(a.action_type == "submit_bid" for a in ts_b.allowed_actions)


def test_auction_random_mode_max_rounds():
    """In RANDOM mode, max_rounds still enforced (1 round = N actions)."""
    from arena.games.first_price_auction import FirstPriceAuctionGame
    from arena.spec import TurnOrder

    game = FirstPriceAuctionGame(max_rounds=1, turn_order=TurnOrder.RANDOM)
    spec = game.spec()
    match = create_match("random_mr", "first-price-auction", spec, ["a", "b", "c"])
    game._ensure_valuations(match)
    # 3 passes = 1 round with 3 agents → triggers max_rounds
    game.apply_action(match, "a", Action(action_type="pass", payload={}))
    game.apply_action(match, "b", Action(action_type="pass", payload={}))
    game.apply_action(match, "c", Action(action_type="pass", payload={}))
    assert match.status == MatchStatus.FINISHED
    assert match.outcome["reason"] == "max_rounds_exceeded"


def test_auction_round_robin_rejects_out_of_turn():
    """In ROUND_ROBIN mode, out-of-turn actions are rejected."""
    from arena.games.first_price_auction import FirstPriceAuctionGame
    from arena.spec import TurnOrder

    game = FirstPriceAuctionGame(valuations={"a": 60, "b": 80}, turn_order=TurnOrder.ROUND_ROBIN)
    spec = game.spec()
    match = create_match("rr1", "first-price-auction", spec, ["a", "b"])
    game._ensure_valuations(match)
    # It's a's turn (index 0); b trying to act should fail
    result = game.apply_action(match, "b", Action(action_type="submit_bid", payload={"bid": 50}))
    assert result.ok is False
    assert result.error == "not_your_turn"
