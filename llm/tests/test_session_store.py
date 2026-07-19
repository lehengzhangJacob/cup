import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.session_store import ConversationStore


def test_store_bounds_turns_and_message_size():
    store = ConversationStore(
        ttl_seconds=60,
        max_sessions=5,
        max_turns=2,
        max_message_chars=5,
    )
    store.append("s1", "first-user", "first-answer")
    store.append("s1", "second-user", "second-answer")
    store.append("s1", "third-user", "third-answer")

    turns = store.get("s1")
    assert len(turns) == 2
    assert turns[-1].user == "-user"
    assert turns[-1].assistant == "nswer"


def test_store_expires_and_evicts_lru_sessions():
    now = [0.0]
    store = ConversationStore(
        ttl_seconds=10,
        max_sessions=2,
        max_turns=2,
        max_message_chars=100,
        clock=lambda: now[0],
    )
    store.append("s1", "u", "a")
    store.append("s2", "u", "a")
    store.get("s1")
    store.append("s3", "u", "a")
    assert store.get("s2") == []
    assert store.get("s1")

    now[0] = 11.0
    assert store.get("s1") == []
    assert store.stats() == {"sessions": 0, "turns": 0}


def test_clear_session_isolated():
    store = ConversationStore()
    store.append("a", "u", "a")
    store.append("b", "u", "b")
    assert store.clear("a") is True
    assert store.get("a") == []
    assert store.get("b")
