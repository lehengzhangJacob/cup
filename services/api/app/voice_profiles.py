from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]

# A voice profile is a business-level identifier.  The local and cloud
# engines receive different implementation identifiers, but both are cloned
# from the same reference recording.  This keeps the guide's voice stable
# when the visitor switches between local and cloud AI routes.
_LINGXI_REFERENCE = Path(
    os.getenv(
        "LINGXI_VOICE_REFERENCE",
        str(PROJECT_ROOT / "data/voice_profiles/lingxi_female_reference.wav"),
    )
).expanduser()

VOICE_PROFILES: dict[str, dict[str, Any]] = {
    "lingxi_female_v1": {
        "id": "lingxi_female_v1",
        "label": "灵曦清雅女声 · 本地/云端统一",
        "description": "同一参考音频分别驱动本地 GLM-TTS 与云端 GLM-TTS-Clone",
        "local_reference_audio": str(_LINGXI_REFERENCE),
        "reference_text": "您好，我是灵山景区的智能导游，很高兴陪伴您参观游览。",
        "cloud_voice": os.getenv(
            "ZHIPU_TTS_LINGXI_VOICE",
            "f801cc06-9229-59fe-b633-528a0109a858",
        ).strip(),
        "sample_rate": 24000,
        "gender": "female",
        "style": "清雅讲解",
        "license": "参考音频由本地 Piper 华研模型生成，用作本项目统一音色锚点",
        "paired": True,
    },
    "lingyue_female_v1": {
        "id": "lingyue_female_v1",
        "label": "灵悦亲和女声 · 本地/云端统一",
        "description": "明亮亲和，适合亲子路线与互动讲解",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingyue_female_reference.wav"
        ),
        "reference_text": "您好，我是灵山景区的智能导游，很高兴陪伴您参观游览。",
        "cloud_voice": os.getenv(
            "ZHIPU_TTS_LINGYUE_VOICE",
            "72abf896-9182-5008-b109-62aa17e24019",
        ).strip(),
        "sample_rate": 24000,
        "gender": "female",
        "style": "亲和互动",
        "license": "参考音频由智谱 GLM-TTS 彤彤系统音色生成，并注册为本项目克隆音色",
        "paired": True,
    },
    "lingyun_male_v1": {
        "id": "lingyun_male_v1",
        "label": "灵云沉稳男声 · 本地/云端统一",
        "description": "同一 CC0 来源参考音频分别驱动本地与云端 GLM-TTS",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingyun_male_reference.wav"
        ),
        "reference_text": "您好，我是灵山景区的智能导游，很高兴陪伴您参观游览。",
        "cloud_voice": os.getenv(
            "ZHIPU_TTS_LINGYUN_VOICE",
            "a5ce70d3-b4d4-5cca-a207-62a9e725c4a0",
        ).strip(),
        "sample_rate": 24000,
        "gender": "male",
        "style": "沉稳历史",
        "license": "参考音频由 Piper 超文生成；训练数据集标注为 CC0",
        "paired": True,
    },
    "lingchuan_male_v1": {
        "id": "lingchuan_male_v1",
        "label": "灵川青年男声 · 本地/云端统一",
        "description": "清朗自然，适合休闲路线与年轻游客",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingchuan_male_reference.wav"
        ),
        "reference_text": "您好，我是灵山景区的智能导游，很高兴陪伴您参观游览。",
        "cloud_voice": os.getenv(
            "ZHIPU_TTS_LINGCHUAN_VOICE",
            "5307a424-7fcf-5be1-a15b-88358ee20f54",
        ).strip(),
        "sample_rate": 24000,
        "gender": "male",
        "style": "青年休闲",
        "license": "参考音频由智谱 GLM-TTS 小陈系统音色生成，并注册为本项目克隆音色",
        "paired": True,
    },
}

DEFAULT_VOICE_PROFILE = os.getenv(
    "DEFAULT_VOICE_PROFILE", "lingxi_female_v1"
).strip()

# Existing deployments stored provider-specific names in avatar_settings.
# Migrate them logically at read time so old databases do not expose a voice
# that the local engine cannot reproduce.
LEGACY_VOICE_ALIASES = {
    "female": DEFAULT_VOICE_PROFILE,
    "male": DEFAULT_VOICE_PROFILE,
    "tongtong": DEFAULT_VOICE_PROFILE,
    "chuichui": DEFAULT_VOICE_PROFILE,
}


def normalize_voice_profile(voice: str | None) -> str:
    value = str(voice or "").strip()
    value = LEGACY_VOICE_ALIASES.get(value, value)
    if value not in VOICE_PROFILES:
        return DEFAULT_VOICE_PROFILE
    return value


def voice_profile(voice: str | None) -> dict[str, Any]:
    return VOICE_PROFILES[normalize_voice_profile(voice)]


def cloud_voice_id(voice: str | None) -> str:
    profile = voice_profile(voice)
    cloud_voice = str(profile.get("cloud_voice") or "").strip()
    if not cloud_voice:
        raise RuntimeError(f"音色 {profile['label']} 尚未注册云端克隆音色")
    return cloud_voice


def public_voice_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "description": profile["description"],
            "gender": profile.get("gender", ""),
            "style": profile.get("style", ""),
            "paired": bool(profile.get("paired")),
            "local_ready": Path(profile["local_reference_audio"]).is_file(),
            "cloud_ready": bool(str(profile.get("cloud_voice") or "").strip()),
            "license": profile.get("license", ""),
        }
        for profile in VOICE_PROFILES.values()
    ]
