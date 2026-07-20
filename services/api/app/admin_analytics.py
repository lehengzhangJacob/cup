from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .demo_data import demo_data_status
from .emotion_analysis import EMOTION_LABELS, analyze_text


BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


TOPIC_KEYWORDS = {
    "灵山大佛": ("灵山大佛", "大佛", "抱佛脚"),
    "灵山梵宫": ("梵宫", "吉祥颂"),
    "九龙灌浴": ("九龙灌浴", "灌浴"),
    "祥符禅寺": ("祥符禅寺", "禅寺"),
    "五印坛城": ("五印坛城", "坛城"),
    "路线与定位": ("路线", "怎么走", "导航", "定位", "下一站"),
    "门票与开放": ("门票", "票价", "开放", "几点", "表演时间"),
    "餐饮与休息": ("餐饮", "素斋", "吃饭", "休息", "厕所"),
}


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _last_days(days: int = 7) -> list[str]:
    today = datetime.now(BUSINESS_TIMEZONE).date()
    return [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(days - 1, -1, -1)
    ]


def _business_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BUSINESS_TIMEZONE).date().isoformat()


def _sentiment_counter() -> dict[str, int]:
    return {"positive": 0, "neutral": 0, "negative": 0}


def _count_sentiment(counter: dict[str, int], value: Any) -> None:
    label = str(value or "neutral")
    if label not in counter:
        label = "neutral"
    counter[label] += 1


def _topic_counts(questions: list[str]) -> list[dict[str, Any]]:
    result = []
    for name, keywords in TOPIC_KEYWORDS.items():
        count = sum(
            1
            for question in questions
            if any(keyword in question for keyword in keywords)
        )
        result.append({"name": name, "count": count})
    return sorted(result, key=lambda item: item["count"], reverse=True)


def _emotion_rows(conn: sqlite3.Connection, limit: int = 500) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT id, session_id, source, transcript, rating, media_kind,
               emotion_label, emotion_scores, sentiment, valence, confidence,
               aspects, status, model_name, analysis_mode, error,
               created_at, completed_at
          FROM emotion_events
         WHERE source LIKE 'dialogue-%'
         ORDER BY created_at DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()


def build_overview(
    conn: sqlite3.Connection,
    routes: list[dict[str, Any]],
) -> dict[str, Any]:
    days = _last_days()
    today, week_start = days[-1], days[0]
    demo_data = demo_data_status(conn)
    service_turns, unique_visitors = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM chat_logs WHERE role='user'"
    ).fetchone()
    today_visitors = conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM chat_logs "
        "WHERE role='user' AND date(created_at, '+8 hours')=?",
        (today,),
    ).fetchone()[0]
    week_visitors = conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM chat_logs "
        "WHERE role='user' AND date(created_at, '+8 hours')>=?",
        (week_start,),
    ).fetchone()[0]

    user_rows = conn.execute(
        "SELECT session_id, content, meta, created_at FROM chat_logs "
        "WHERE role='user' ORDER BY created_at DESC LIMIT 1000"
    ).fetchall()
    assistant_rows = conn.execute(
        "SELECT meta FROM chat_logs WHERE role='assistant' "
        "ORDER BY created_at DESC LIMIT 1000"
    ).fetchall()
    feedback_rows = conn.execute(
        "SELECT attraction_id, scenic_area, attraction_name, rating, comment, "
        "sentiment, created_at, source FROM feedback "
        "ORDER BY created_at DESC LIMIT 1000"
    ).fetchall()
    emotion_rows = _emotion_rows(conn)

    feedback_count, avg_satisfaction = conn.execute(
        "SELECT COUNT(*), AVG(rating) FROM feedback"
    ).fetchone()
    questions = [str(row[1] or "") for row in user_rows]
    hot_topics = _topic_counts(questions)

    daily_service = []
    satisfaction_trend = []
    sentiment_trend = []
    for day in days:
        turns, visitors = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM chat_logs "
            "WHERE role='user' AND date(created_at, '+8 hours')=?",
            (day,),
        ).fetchone()
        daily_service.append({"date": day, "turns": turns, "visitors": visitors})
        ratings = [
            int(row[3])
            for row in feedback_rows
            if _business_date(row[6]) == day
        ]
        satisfaction_trend.append(
            {
                "date": day,
                "score": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "count": len(ratings),
            }
        )
        daily_sentiment = _sentiment_counter()
        for row in emotion_rows:
            has_signal = bool(row[6]) or float(row[10] or 0) > 0
            if (
                _business_date(row[16]) == day
                and row[12] == "completed"
                and has_signal
            ):
                _count_sentiment(daily_sentiment, row[8])
        for row in feedback_rows:
            if _business_date(row[6]) == day:
                _count_sentiment(daily_sentiment, row[5])
        sentiment_trend.append({"date": day, **daily_sentiment})

    query_sentiment = _sentiment_counter()
    for _, content, meta_text, _ in user_rows[:500]:
        meta = _json(meta_text, {})
        sentiment = meta.get("sentiment")
        if not sentiment:
            sentiment = analyze_text(str(content or ""))["sentiment"]
        _count_sentiment(query_sentiment, sentiment)

    feedback_sentiment = _sentiment_counter()
    aspect_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for _, _, _, rating, comment, sentiment, _, _ in feedback_rows:
        _count_sentiment(feedback_sentiment, sentiment)
        for aspect in analyze_text(str(comment or ""), int(rating))["aspects"]:
            aspect_stats[aspect["name"]][aspect["sentiment"]] += 1

    emotion_sentiment = _sentiment_counter()
    emotion_distribution = {label: 0 for label in EMOTION_LABELS}
    status_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    for row in emotion_rows:
        status_counts[str(row[12] or "unknown")] += 1
        mode_counts[str(row[14] or "unknown")] += 1
        if row[12] != "completed":
            continue
        if not row[6] and float(row[10] or 0) <= 0:
            continue
        _count_sentiment(emotion_sentiment, row[8])
        label = str(row[6] or "")
        if label in emotion_distribution:
            emotion_distribution[label] += 1
        for aspect in _json(row[11], []):
            name = str(aspect.get("name") or "")
            sentiment = str(aspect.get("sentiment") or "neutral")
            if name:
                aspect_stats[name][sentiment] += 1

    combined_sentiment = _sentiment_counter()
    # A tourist question is not automatically a satisfaction signal. The
    # report therefore combines only explicit ratings/comments and dialogue
    # emotion events that contain actual emotional evidence.
    for source in (feedback_sentiment, emotion_sentiment):
        for key in combined_sentiment:
            combined_sentiment[key] += source[key]

    latencies = []
    for (meta_text,) in assistant_rows:
        latency = _json(meta_text, {}).get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(float(latency))
    avg_response_ms = round(sum(latencies) / len(latencies)) if latencies else None

    aspect_insights = []
    for name, counts in aspect_stats.items():
        total = sum(counts.values())
        aspect_insights.append(
            {
                "name": name,
                "count": total,
                "positive": counts["positive"],
                "neutral": counts["neutral"],
                "negative": counts["negative"],
                "negative_rate": round(counts["negative"] / total * 100, 1)
                if total
                else 0,
            }
        )
    aspect_insights.sort(
        key=lambda item: (item["negative"], item["count"]),
        reverse=True,
    )

    attraction_satisfaction = [
        {
            "attraction_id": row[0],
            "scenic_area": row[1],
            "attraction_name": row[2],
            "count": int(row[3]),
            "avg_satisfaction": round(float(row[4]), 2),
            "low_rating_count": int(row[5]),
        }
        for row in conn.execute(
            """
            SELECT attraction_id, scenic_area, attraction_name, COUNT(*),
                   AVG(rating), SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END)
              FROM feedback
             WHERE attraction_id IS NOT NULL
             GROUP BY attraction_id, scenic_area, attraction_name
             ORDER BY COUNT(*) DESC, AVG(rating) DESC, attraction_name
            """
        ).fetchall()
    ]

    suggestion_entries: list[dict[str, Any]] = []

    def add_suggestion(
        title: str, text: str, *, sample_count: int, severity: str, evidence: list[str]
    ) -> None:
        suggestion_entries.append(
            {
                "title": title,
                "text": text,
                "sample_count": sample_count,
                "severity": severity,
                "evidence": evidence,
                "time_range": "近 7 天",
            }
        )

    if aspect_insights and aspect_insights[0]["negative"]:
        top = aspect_insights[0]
        add_suggestion(
            "优先复核负向服务方面",
            f"“{top['name']}”出现 {top['negative']} 条负向反馈（负向率 {top['negative_rate']}%），建议优先复核对应服务流程。",
            sample_count=top["count"],
            severity="high" if top["negative_rate"] >= 35 else "medium",
            evidence=[f"负向 {top['negative']} 条", f"总样本 {top['count']} 条"],
        )
    if avg_response_ms is not None and avg_response_ms > 5000:
        add_suggestion(
            "检查响应链路",
            f"近期平均回答耗时 {avg_response_ms}ms，已超过 5 秒体验目标，建议检查模型首句延迟和语音合成队列。",
            sample_count=len(latencies),
            severity="high",
            evidence=[f"平均耗时 {avg_response_ms}ms", f"延迟样本 {len(latencies)} 条"],
        )
    if avg_satisfaction is not None and avg_satisfaction < 3.5:
        add_suggestion(
            "回看低分会话",
            f"累计明确满意度为 {avg_satisfaction:.2f}/5，建议回看低分会话及证据文本。",
            sample_count=int(feedback_count or 0),
            severity="medium",
            evidence=[f"评分样本 {int(feedback_count or 0)} 条"],
        )
    route_topic = next((item for item in hot_topics if item["name"] == "路线与定位"), None)
    if route_topic and route_topic["count"]:
        add_suggestion(
            "强化定位引导",
            f"最近 {route_topic['count']} 次咨询涉及路线或定位，可在入口强化分众路线和二维码定位提示。",
            sample_count=route_topic["count"],
            severity="low",
            evidence=[f"路线/定位咨询 {route_topic['count']} 次"],
        )
    if not suggestion_entries:
        add_suggestion(
            "持续采集有效反馈",
            "当前未发现集中负面问题；建议继续收集景点明确评分和游客对话情绪信号。",
            sample_count=int(feedback_count or 0),
            severity="low",
            evidence=["暂无满足触发阈值的问题"],
        )
    suggestions = [entry["text"] for entry in suggestion_entries]
    completed_emotion_count = sum(
        count for status, count in status_counts.items() if status == "completed"
    )
    data_quality = {
        "feedback_count": int(feedback_count or 0),
        "emotion_completed_count": int(completed_emotion_count),
        "satisfaction_trend_ready": int(feedback_count or 0) >= 5,
        "minimum_feedback_for_trend": 5,
        "contains_demo_data": demo_data["active"],
        "note": (
            "当前实时指标包含明确标注的答辩演示数据；可在数据概览中一键清除。"
            if demo_data["active"]
            else "实时指标只统计游客端真实对话、情绪和主动评分；赛题 XLSX 历史样本在历史分析页单独展示。"
        ),
    }

    recent_events = []
    for row in emotion_rows[:20]:
        recent_events.append(
            {
                "id": row[0],
                "session_id": row[1],
                "source": row[2],
                "transcript": row[3],
                "rating": row[4],
                "media_kind": row[5],
                "emotion": row[6],
                "scores": _json(row[7], {}),
                "sentiment": row[8],
                "valence": row[9],
                "confidence": row[10],
                "aspects": _json(row[11], []),
                "status": row[12],
                "model": row[13],
                "analysis_mode": row[14],
                "error": row[15],
                "created_at": row[16],
                "completed_at": row[17],
            }
        )

    return {
        "service_turns": int(service_turns or 0),
        "unique_visitors": int(unique_visitors or 0),
        "today_visitors": int(today_visitors or 0),
        "week_visitors": int(week_visitors or 0),
        "avg_satisfaction": round(float(avg_satisfaction), 2)
        if avg_satisfaction is not None
        else None,
        "feedback_count": int(feedback_count or 0),
        "avg_response_ms": avg_response_ms,
        "hot_topics": hot_topics,
        "sentiment": combined_sentiment,
        "sentiment_sources": {
            "query_tone": query_sentiment,
            "feedback": feedback_sentiment,
            "dialogue_emotion": emotion_sentiment,
        },
        "emotion_distribution": emotion_distribution,
        "emotion_job_status": dict(status_counts),
        "analysis_modes": dict(mode_counts),
        "aspect_insights": aspect_insights,
        "attraction_satisfaction": attraction_satisfaction,
        "daily_service": daily_service,
        "satisfaction_trend": satisfaction_trend,
        "sentiment_trend": sentiment_trend,
        "recent_questions": questions[:10],
        "recent_feedback": [
            {
                "attraction_id": row[0],
                "scenic_area": row[1],
                "attraction_name": row[2],
                "rating": row[3],
                "comment": row[4],
                "sentiment": row[5],
                "created_at": row[6],
                "source": row[7],
            }
            for row in feedback_rows[:10]
        ],
        "recent_emotion_events": recent_events,
        "service_suggestions": suggestions,
        "service_suggestion_evidence": suggestion_entries,
        "data_quality": data_quality,
        "routes": routes,
        "demo_data": demo_data,
    }
