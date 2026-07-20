import sqlite3

from app.tourism_analytics import _content_key, ensure_tourism_schema


def test_repeated_attraction_description_has_stable_dimension_key():
    row = {
        "attraction_name": "灵山大佛",
        "attraction_type": "文化景观",
        "attraction_content": "一段重复出现的景点介绍",
    }
    assert _content_key(row) == _content_key(dict(row))


def test_tourism_schema_has_separate_content_dimension():
    conn = sqlite3.connect(":memory:")
    ensure_tourism_schema(conn)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tourism_visits" in names
    assert "tourism_attraction_contents" in names
