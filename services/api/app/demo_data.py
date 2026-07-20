from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta, timezone
from typing import Any

from .attractions import attraction_by_id


BUSINESS_TIMEZONE = timezone(timedelta(hours=8))
DEMO_PREFIX = "answer-demo-"
DEMO_FEEDBACK_SOURCE = "demo"
DEMO_EMOTION_SOURCE = "dialogue-demo"


QUESTIONS = (
    ("灵山大佛有多高，铜像有什么看点？", "灵山大佛通高八十八米。建议从大照壁沿菩提大道步行前往，并预留登台参观时间。", "neutral"),
    ("九龙灌浴今天几点有表演？", "表演场次可能随季节和客流调整，请以景区当日公告为准；我也可以继续帮您规划前后游览顺序。", "neutral"),
    ("只有两个小时，推荐一条不绕路的路线。", "推荐大照壁、九龙灌浴、祥符禅寺、灵山大佛的精华路线，先看演出再登大佛会更顺路。", "neutral"),
    ("灵山梵宫的建筑和文化特色是什么？", "灵山梵宫以佛教文化艺术展示为核心，穹顶、廊厅和大型艺术陈设都值得重点欣赏。", "positive"),
    ("带老人和孩子怎么走更轻松？", "建议减少折返，优先选择观光车衔接九龙灌浴、梵宫和大佛区域，并安排中途休息。", "neutral"),
    ("五印坛城适合拍照吗？", "适合。坛城建筑色彩鲜明，广场视野开阔，傍晚光线通常更柔和。", "positive"),
    ("景区哪里能吃素斋和休息？", "可关注无尽意斋及游客服务点，具体营业时间请以现场公告为准。", "neutral"),
    ("从灵山胜境去拈花湾怎么安排夜游？", "可以白天游览灵山胜境，傍晚前往拈花湾，在香月花街和五灯湖一带安排夜游。", "positive"),
    ("祥符禅寺到灵山大佛怎么走？", "从祥符禅寺继续沿主游线向上即可到达大佛区域，现场也可结合导览牌确认无障碍路线。", "neutral"),
    ("拈花湾晚上有哪些值得看的地方？", "推荐香月花街、拈花广场和五灯湖，夜间演艺时间请以当日节目单为准。", "positive"),
)

ATTRACTIONS = (
    ("LS-011", 5, "大佛很震撼，讲解清楚，路线也很好走。"),
    ("LS-006", 4, "九龙灌浴表演很精彩，就是排队稍久。"),
    ("LS-013", 5, "梵宫建筑漂亮，文化内容丰富，很值得推荐。"),
    ("LS-014", 4, "五印坛城拍照很好看，现场介绍也很清楚。"),
    ("LS-010", 5, "环境安静，工作人员服务很好。"),
    ("LS-016", 4, "素斋不错，休息和吃饭都比较方便。"),
    ("NH-003", 5, "香月花街夜景漂亮，路线推荐很实用。"),
    ("NH-005", 4, "五灯湖夜景不错，数字人讲解很有趣。"),
    ("LS-006", 3, "表演不错，但排队和客流引导还可以更清楚。"),
    ("LS-011", 4, "整体满意，登大佛路线有一点累。"),
    ("NH-ALL", 5, "夜游体验很好，推荐傍晚过来。"),
    ("LS-ALL", 2, "周末人多拥挤，停车和排队等待时间太长。"),
)

EMOTIONS = (
    ("happy", "positive", 0.82, 0.93, "景色很漂亮，讲解也很清楚。", "讲解内容"),
    ("neutral", "neutral", 0.02, 0.84, "我想确认下一站怎么走。", "路线推荐"),
    ("surprise", "positive", 0.68, 0.89, "大佛比想象中更震撼。", "讲解内容"),
    ("happy", "positive", 0.76, 0.91, "路线推荐很方便，谢谢。", "路线推荐"),
    ("neutral", "neutral", 0.08, 0.81, "请介绍一下今天的表演时间。", "讲解内容"),
    ("sad", "negative", -0.58, 0.86, "排队太久，差点错过表演。", "排队与客流"),
    ("angry", "negative", -0.79, 0.92, "停车等待太久，现场也很拥挤。", "交通停车"),
)

DAILY_SESSION_COUNTS = (3, 4, 5, 6, 8, 10, 12)
DAILY_FEEDBACK_COUNTS = (2, 2, 3, 3, 4, 4, 5)
DAILY_EMOTION_COUNTS = (1, 2, 2, 3, 3, 4, 6)


def _utc_timestamp(
    day: Any,
    hour: int,
    minute: int = 0,
    *,
    anchor: datetime | None = None,
    fallback_minutes: int = 1,
) -> str:
    local = datetime.combine(day, time(hour=hour, minute=minute), BUSINESS_TIMEZONE)
    if anchor is not None and local > anchor:
        local = anchor - timedelta(minutes=max(1, fallback_minutes))
    return local.astimezone(timezone.utc).isoformat()


def demo_data_status(conn: sqlite3.Connection) -> dict[str, Any]:
    question_count, session_count = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM chat_logs "
        "WHERE role='user' AND session_id LIKE ?",
        (f"{DEMO_PREFIX}%",),
    ).fetchone()
    feedback_count = conn.execute(
        "SELECT COUNT(*) FROM feedback WHERE source=?",
        (DEMO_FEEDBACK_SOURCE,),
    ).fetchone()[0]
    emotion_count = conn.execute(
        "SELECT COUNT(*) FROM emotion_events WHERE source=?",
        (DEMO_EMOTION_SOURCE,),
    ).fetchone()[0]
    generated_at = conn.execute(
        """
        SELECT MAX(created_at) FROM (
            SELECT created_at FROM chat_logs WHERE session_id LIKE ?
            UNION ALL SELECT created_at FROM feedback WHERE source=?
            UNION ALL SELECT created_at FROM emotion_events WHERE source=?
        )
        """,
        (f"{DEMO_PREFIX}%", DEMO_FEEDBACK_SOURCE, DEMO_EMOTION_SOURCE),
    ).fetchone()[0]
    return {
        "active": bool(question_count or feedback_count or emotion_count),
        "label": "答辩演示数据",
        "session_count": int(session_count or 0),
        "question_count": int(question_count or 0),
        "feedback_count": int(feedback_count or 0),
        "emotion_count": int(emotion_count or 0),
        "generated_at": generated_at,
    }


def _delete_demo_rows(conn: sqlite3.Connection) -> dict[str, int]:
    chat_rows = conn.execute(
        "DELETE FROM chat_logs WHERE session_id LIKE ?",
        (f"{DEMO_PREFIX}%",),
    ).rowcount
    feedback_rows = conn.execute(
        "DELETE FROM feedback WHERE source=?",
        (DEMO_FEEDBACK_SOURCE,),
    ).rowcount
    emotion_rows = conn.execute(
        "DELETE FROM emotion_events WHERE source=?",
        (DEMO_EMOTION_SOURCE,),
    ).rowcount
    return {
        "chat_rows": int(chat_rows or 0),
        "feedback_rows": int(feedback_rows or 0),
        "emotion_rows": int(emotion_rows or 0),
    }


def clear_demo_data(conn: sqlite3.Connection) -> dict[str, Any]:
    deleted = _delete_demo_rows(conn)
    conn.commit()
    return {"ok": True, "deleted": deleted, **demo_data_status(conn)}


def seed_demo_data(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace the synthetic defence dataset without touching live rows."""
    anchor = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TIMEZONE)
    days = [anchor.date() - timedelta(days=offset) for offset in range(6, -1, -1)]
    _delete_demo_rows(conn)

    question_index = 0
    sessions: list[tuple[str, Any, int]] = []
    for day_index, (day, session_total) in enumerate(zip(days, DAILY_SESSION_COUNTS)):
        for visitor_index in range(session_total):
            session_id = f"{DEMO_PREFIX}{day_index + 1:02d}-{visitor_index + 1:02d}"
            hour = 9 + (visitor_index * 7 + day_index) % 9
            minute = (visitor_index * 11 + day_index * 3) % 60
            created_at = _utc_timestamp(
                day,
                hour,
                minute,
                anchor=anchor,
                fallback_minutes=(visitor_index + 1) * 4,
            )
            question, answer, sentiment = QUESTIONS[question_index % len(QUESTIONS)]
            latency_ms = 620 + (question_index * 137) % 2600
            conn.execute(
                "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
                (
                    f"{session_id}-user",
                    session_id,
                    "user",
                    question,
                    json.dumps(
                        {"source": "demo", "input_mode": "text", "sentiment": sentiment},
                        ensure_ascii=False,
                    ),
                    created_at,
                ),
            )
            conn.execute(
                "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
                (
                    f"{session_id}-assistant",
                    session_id,
                    "assistant",
                    answer,
                    json.dumps(
                        {"source": "demo", "latency_ms": latency_ms},
                        ensure_ascii=False,
                    ),
                    created_at,
                ),
            )
            sessions.append((session_id, day, visitor_index))
            question_index += 1

    feedback_index = 0
    session_cursor = 0
    for day_index, (day, feedback_total) in enumerate(zip(days, DAILY_FEEDBACK_COUNTS)):
        for item_index in range(feedback_total):
            attraction_id, rating, comment = ATTRACTIONS[feedback_index % len(ATTRACTIONS)]
            attraction = attraction_by_id(attraction_id)
            if attraction is None:
                raise RuntimeError(f"Unknown demo attraction: {attraction_id}")
            session_id = sessions[session_cursor % len(sessions)][0]
            sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
            created_at = _utc_timestamp(
                day,
                10 + item_index % 8,
                (item_index * 13 + 7) % 60,
                anchor=anchor,
                fallback_minutes=(item_index + 1) * 6 + 2,
            )
            conn.execute(
                """
                INSERT INTO feedback
                    (id, session_id, attraction_id, scenic_area, attraction_name,
                     rating, comment, sentiment, source, emotion_event_id, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"{DEMO_PREFIX}feedback-{day_index + 1:02d}-{item_index + 1:02d}",
                    session_id,
                    attraction_id,
                    attraction["scenic_area"],
                    attraction["name"],
                    rating,
                    comment,
                    sentiment,
                    DEMO_FEEDBACK_SOURCE,
                    None,
                    created_at,
                ),
            )
            feedback_index += 1
            session_cursor += 2

    emotion_index = 0
    session_cursor = 1
    for day_index, (day, emotion_total) in enumerate(zip(days, DAILY_EMOTION_COUNTS)):
        for item_index in range(emotion_total):
            emotion, sentiment, valence, confidence, transcript, aspect = EMOTIONS[
                emotion_index % len(EMOTIONS)
            ]
            scores = {label: 0.01 for label in ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")}
            scores[emotion] = confidence
            session_id = sessions[session_cursor % len(sessions)][0]
            created_at = _utc_timestamp(
                day,
                11 + item_index % 7,
                (item_index * 17 + 5) % 60,
                anchor=anchor,
                fallback_minutes=(item_index + 1) * 5 + 1,
            )
            conn.execute(
                """
                INSERT INTO emotion_events
                    (id, session_id, source, transcript, rating, media_kind,
                     emotion_label, emotion_scores, sentiment, valence, confidence,
                     aspects, status, model_name, analysis_mode, error,
                     created_at, completed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"{DEMO_PREFIX}emotion-{day_index + 1:02d}-{item_index + 1:02d}",
                    session_id,
                    DEMO_EMOTION_SOURCE,
                    transcript,
                    None,
                    "audio",
                    emotion,
                    json.dumps(scores, ensure_ascii=False),
                    sentiment,
                    valence,
                    confidence,
                    json.dumps(
                        [{"name": aspect, "sentiment": sentiment, "keywords": []}],
                        ensure_ascii=False,
                    ),
                    "completed",
                    "demo-fixture",
                    "demo",
                    None,
                    created_at,
                    created_at,
                ),
            )
            emotion_index += 1
            session_cursor += 2

    conn.commit()
    return {"ok": True, "replaced": True, **demo_data_status(conn)}
