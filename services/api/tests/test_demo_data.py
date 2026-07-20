import sqlite3
from datetime import datetime, timezone

from app.demo_data import clear_demo_data, demo_data_status, seed_demo_data


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE chat_logs (
          id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
          meta TEXT, created_at TEXT
        );
        CREATE TABLE feedback (
          id TEXT PRIMARY KEY, session_id TEXT, attraction_id TEXT,
          scenic_area TEXT, attraction_name TEXT, rating INTEGER, comment TEXT,
          sentiment TEXT, source TEXT, emotion_event_id TEXT, created_at TEXT
        );
        CREATE TABLE emotion_events (
          id TEXT PRIMARY KEY, session_id TEXT, source TEXT, transcript TEXT,
          rating INTEGER, media_kind TEXT, emotion_label TEXT,
          emotion_scores TEXT, sentiment TEXT, valence REAL, confidence REAL,
          aspects TEXT, status TEXT, model_name TEXT, analysis_mode TEXT,
          error TEXT, created_at TEXT, completed_at TEXT
        );
        """
    )
    return conn


def _insert_live_rows(conn: sqlite3.Connection) -> None:
    created_at = "2026-07-20T02:00:00+00:00"
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        ("live-chat", "live-session", "user", "真实提问", "{}", created_at),
    )
    conn.execute(
        "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "live-feedback", "live-session", "LS-011", "灵山胜境",
            "灵山大佛", 5, "真实评价", "positive", "live", None, created_at,
        ),
    )
    conn.execute(
        "INSERT INTO emotion_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "live-emotion", "live-session", "dialogue-voice", "真实情绪",
            None, "audio", "happy", '{"happy":0.9}', "positive", 0.8,
            0.9, "[]", "completed", "model", "audio-text", None,
            created_at, created_at,
        ),
    )
    conn.commit()


def test_demo_seed_is_repeatable_and_clear_preserves_live_rows():
    conn = _database()
    _insert_live_rows(conn)
    now = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)

    first = seed_demo_data(conn, now=now)
    second = seed_demo_data(conn, now=now)

    assert first["active"] is True
    assert first["session_count"] == 48
    assert first["question_count"] == 48
    assert first["feedback_count"] == 23
    assert first["emotion_count"] == 21
    assert second["question_count"] == first["question_count"]
    assert conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0] == 97
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 24
    assert conn.execute("SELECT COUNT(*) FROM emotion_events").fetchone()[0] == 22
    latest_demo = conn.execute(
        "SELECT MAX(created_at) FROM chat_logs WHERE session_id LIKE 'answer-demo-%'"
    ).fetchone()[0]
    assert datetime.fromisoformat(latest_demo) <= now

    cleared = clear_demo_data(conn)

    assert cleared["active"] is False
    assert demo_data_status(conn)["question_count"] == 0
    assert conn.execute("SELECT id FROM chat_logs").fetchall() == [("live-chat",)]
    assert conn.execute("SELECT id FROM feedback").fetchall() == [("live-feedback",)]
    assert conn.execute("SELECT id FROM emotion_events").fetchall() == [("live-emotion",)]
