"""Deterministic, auditable emotional-response policy for the guide avatar.

The emotion classifier identifies the visitor's state.  This module decides
how the *guide* should respond; it deliberately does not ask the generative
model to invent a JSON control protocol.  Keeping the policy here makes the
reaction explainable in the administration reports and stable in demos.
"""
from __future__ import annotations

from typing import Any, Optional


_REACTIONS: dict[str, dict[str, Any]] = {
    "care": {
        "id": "care",
        "label": "关切回应",
        "expression": "gentle",
        "voice_speed": 0.94,
        "tone": "耐心、放缓语速",
        "prefix": "抱歉让您感到不便，我会尽量帮您解决。",
    },
    "comfort": {
        "id": "comfort",
        "label": "安抚回应",
        "expression": "gentle",
        "voice_speed": 0.92,
        "tone": "温和、安抚",
        "prefix": "别担心，我陪您一起看看怎么安排更合适。",
    },
    "celebrate": {
        "id": "celebrate",
        "label": "愉悦互动",
        "expression": "smile",
        "voice_speed": 1.04,
        "tone": "明快、亲切",
        "prefix": "",
    },
    "engage": {
        "id": "engage",
        "label": "惊喜互动",
        "expression": "bright",
        "voice_speed": 1.02,
        "tone": "明快、带一点惊喜",
        "prefix": "",
    },
    "calm": {
        "id": "calm",
        "label": "自然讲解",
        "expression": "natural",
        "voice_speed": 1.0,
        "tone": "自然、清晰",
        "prefix": "",
    },
}


def avatar_reaction(
    *,
    emotion: Optional[str] = None,
    sentiment: Optional[str] = None,
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    """Map a visitor signal to a safe guide response.

    Negative textual sentiment is allowed to trigger care even when the
    seven-class audio model has not finished.  Fear gets a distinct comforting
    response because it is not automatically a service complaint.
    """
    normalized = str(emotion or "").strip().lower()
    normalized_sentiment = str(sentiment or "").strip().lower()
    model_confidence = max(0.0, min(1.0, float(confidence or 0.0)))

    if normalized in {"angry", "disgust"} or normalized_sentiment == "negative":
        chosen = "care"
        reason = "negative_sentiment" if normalized not in {"angry", "disgust"} else normalized
    elif normalized in {"sad", "fear"}:
        chosen = "comfort"
        reason = normalized
    elif normalized == "happy" or normalized_sentiment == "positive":
        chosen = "celebrate"
        reason = "happy" if normalized == "happy" else "positive_sentiment"
    elif normalized == "surprise":
        chosen = "engage"
        reason = "surprise"
    else:
        chosen = "calm"
        reason = "neutral_or_insufficient_signal"

    return {
        **_REACTIONS[chosen],
        "visitor_emotion": normalized or None,
        "visitor_sentiment": normalized_sentiment or "neutral",
        "signal_confidence": round(model_confidence, 4),
        "reason": reason,
    }
