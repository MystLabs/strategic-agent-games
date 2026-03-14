"""Tests for match logging."""

from arena.logging import MatchEvent, MatchLog, MatchLogger
from arena.types import ActionResult, MessageIntent, MessageScope, action_error, action_ok


def test_match_logger_logs_events():
    """log_event adds events to the log."""
    logger = MatchLogger("m1", "ultimatum", ["a", "b"])
    logger.log_event("turn_start", agent_id="a", turn=1)
    logger.log_event("turn_start", agent_id="b", turn=2)
    log = logger.to_log()
    assert len(log.events) == 2
    assert log.events[0].event_type == "turn_start"
    assert log.events[0].agent_id == "a"
    assert log.events[0].data["turn"] == 1
    assert log.events[1].agent_id == "b"


def test_match_logger_save_and_load(tmp_path):
    """Logger saves to JSON and load() reads it back."""
    logger = MatchLogger("m1", "ultimatum", ["a", "b"])
    logger.log_event("start")
    logger.set_outcome({"payoffs": [{"agent_id": "a", "value": 60}]})
    logger.set_metadata(experiment="test")
    path = logger.save(tmp_path)
    assert path.exists()
    loaded = MatchLogger.load(path)
    assert loaded.match_id == "m1"
    assert loaded.game_id == "ultimatum"
    assert loaded.agent_ids == ["a", "b"]
    assert len(loaded.events) == 1
    assert loaded.outcome == {"payoffs": [{"agent_id": "a", "value": 60}]}
    assert loaded.metadata == {"experiment": "test"}


def test_match_log_roundtrip_serialization():
    """MatchLog serializes to JSON and deserializes back identically."""
    log = MatchLog(
        match_id="m1",
        game_id="ultimatum",
        agent_ids=["a", "b"],
        events=[
            MatchEvent(timestamp_ns=12345, event_type="action", agent_id="a", data={"action_type": "submit_offer"}),
        ],
        outcome={"payoffs": []},
        metadata={"seed": 42},
    )
    json_str = log.model_dump_json()
    restored = MatchLog.model_validate_json(json_str)
    assert restored == log


def test_match_logger_log_action_captures_error():
    """log_action captures error details from failed ActionResult."""
    logger = MatchLogger("m1", "ultimatum", ["a", "b"])
    result = action_error("invalid_payload", "my_share must be between 0 and 100")
    logger.log_action("a", "submit_offer", {"my_share": 150}, result)
    log = logger.to_log()
    assert len(log.events) == 1
    ev = log.events[0]
    assert ev.event_type == "action"
    assert ev.data["ok"] is False
    assert ev.data["error"] == "invalid_payload"
    assert ev.data["error_detail"] == "my_share must be between 0 and 100"


def test_match_logger_log_messages():
    """log_messages logs each MessageIntent as a separate event."""
    logger = MatchLogger("m1", "ultimatum", ["a", "b"])
    msgs = [
        MessageIntent(scope=MessageScope.PUBLIC, content="Hello"),
        MessageIntent(scope=MessageScope.PRIVATE, content="Secret", to_agent_ids=["b"]),
    ]
    logger.log_messages("a", msgs)
    log = logger.to_log()
    assert len(log.events) == 2
    assert log.events[0].data["scope"] == "public"
    assert log.events[1].data["scope"] == "private"
    assert log.events[1].data["to_agent_ids"] == ["b"]
