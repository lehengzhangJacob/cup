import sqlite3
from datetime import datetime, timezone

from app.admin_analytics import _business_date, build_overview


def _database():
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


def test_business_date_uses_china_time_for_daily_dashboard():
    assert _business_date("2026-07-18T16:30:00+00:00") == "2026-07-19"


def test_overview_uses_persisted_interactions_feedback_and_emotions():
    conn = _database()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        ("c1", "s1", "user", "九龙灌浴怎么走", '{"sentiment":"neutral"}', now),
    )
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        ("c2", "s1", "assistant", "请沿菩提大道前行", '{"latency_ms":3200}', now),
    )
    conn.execute(
        "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "f1", "s1", "LS-006", "灵山胜境", "九龙灌浴", 2,
            "排队太久了", "negative", "live", None, now,
        ),
    )
    conn.execute(
        "INSERT INTO emotion_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "e1",
            "s1",
            "dialogue-voice",
            "排队太久了",
            2,
            "video_audio",
            "angry",
            '{"angry":0.9}',
            "negative",
            -0.8,
            0.9,
            '[{"name":"排队与客流","sentiment":"negative"}]',
            "completed",
            "emotion_v5_stage2",
            "multimodal",
            None,
            now,
            now,
        ),
    )
    conn.commit()

    result = build_overview(conn, routes=[])

    assert result["service_turns"] == 1
    assert result["unique_visitors"] == 1
    assert result["avg_satisfaction"] == 2.0
    assert result["avg_response_ms"] == 3200
    assert result["emotion_distribution"]["angry"] == 1
    assert result["analysis_modes"]["multimodal"] == 1
    assert result["attraction_satisfaction"][0]["attraction_name"] == "九龙灌浴"
    assert result["sentiment_sources"]["query_tone"]["neutral"] == 1
    assert result["sentiment"]["neutral"] == 0
    assert result["aspect_insights"][0]["name"] == "排队与客流"
    assert result["service_suggestions"]
