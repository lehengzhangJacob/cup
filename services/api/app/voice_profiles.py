from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_TEXT = "您好，我是灵山景区的智能导游，很高兴陪伴您参观游览。"

# Local GLM-TTS profiles are zero-shot references stored with the project.
# They are deliberately independent from the cloud provider's system voices.
VOICE_PROFILES: dict[str, dict[str, Any]] = {
    "lingxi_female_v1": {
        "id": "lingxi_female_v1",
        "label": "灵曦清雅女声",
        "description": "清雅自然，适合文化讲解",
        "local_reference_audio": str(
            Path(
                os.getenv(
                    "LINGXI_VOICE_REFERENCE",
                    str(PROJECT_ROOT / "data/voice_profiles/lingxi_female_reference.wav"),
                )
            ).expanduser()
        ),
        "reference_text": REFERENCE_TEXT,
        "sample_rate": 24000,
        "gender": "female",
        "style": "清雅讲解",
        "license": "参考音频由本地 Piper 华研模型生成，仅用于本地 GLM-TTS 音色锚点",
    },
    "lingyue_female_v1": {
        "id": "lingyue_female_v1",
        "label": "灵悦亲和女声",
        "description": "明亮亲和，适合亲子路线与互动讲解",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingyue_female_reference.wav"
        ),
        "reference_text": REFERENCE_TEXT,
        "sample_rate": 24000,
        "gender": "female",
        "style": "亲和互动",
        "license": "参考音频由智谱 GLM-TTS 彤彤系统音色生成，仅作为本地模型参考",
    },
    "lingyun_male_v1": {
        "id": "lingyun_male_v1",
        "label": "灵云沉稳男声",
        "description": "沉稳从容，适合历史文化讲解",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingyun_male_reference.wav"
        ),
        "reference_text": REFERENCE_TEXT,
        "sample_rate": 24000,
        "gender": "male",
        "style": "沉稳历史",
        "license": "参考音频由 Piper 超文生成；训练数据集标注为 CC0",
    },
    "lingchuan_male_v1": {
        "id": "lingchuan_male_v1",
        "label": "灵川青年男声",
        "description": "清朗自然，适合休闲路线与年轻游客",
        "local_reference_audio": str(
            PROJECT_ROOT / "data/voice_profiles/lingchuan_male_reference.wav"
        ),
        "reference_text": REFERENCE_TEXT,
        "sample_rate": 24000,
        "gender": "male",
        "style": "青年休闲",
        "license": "参考音频由智谱 GLM-TTS 小陈系统音色生成，仅作为本地模型参考",
    },
}

DEFAULT_VOICE_PROFILE = os.getenv(
    "DEFAULT_VOICE_PROFILE", "lingxi_female_v1"
).strip()

LEGACY_VOICE_ALIASES = {
    "female": "lingxi_female_v1",
    "male": "lingyun_male_v1",
    "tongtong": "lingyue_female_v1",
    "chuichui": "lingyue_female_v1",
    "xiaochen": "lingchuan_male_v1",
}

# Cloud speech now uses provider system voices directly. Clone UUIDs are not
# accepted here, which prevents an old private clone from being selected by
# either the admin setting or a visitor request.
CLOUD_SYSTEM_VOICES: dict[str, dict[str, str]] = {
    "female": {
        "id": "female",
        "label": "智谱原生女声（改造前默认）",
        "description": "恢复项目改造前使用的云端女声",
        "gender": "female",
    },
    "male": {
        "id": "male",
        "label": "智谱原生男声",
        "description": "智谱云端原生男声",
        "gender": "male",
    },
    "tongtong": {
        "id": "tongtong",
        "label": "彤彤 · 明亮女声",
        "description": "智谱 GLM-TTS 系统音色",
        "gender": "female",
    },
    "chuichui": {
        "id": "chuichui",
        "label": "锤锤 · 活力音色",
        "description": "智谱 GLM-TTS 系统音色",
        "gender": "neutral",
    },
    "xiaochen": {
        "id": "xiaochen",
        "label": "小陈 · 低沉男声",
        "description": "智谱 GLM-TTS 系统音色",
        "gender": "male",
    },
}

_configured_cloud_voice = os.getenv("ZHIPU_TTS_VOICE", "female").strip()
DEFAULT_CLOUD_VOICE = (
    _configured_cloud_voice
    if _configured_cloud_voice in CLOUD_SYSTEM_VOICES
    else "female"
)


def normalize_voice_profile(voice: str | None) -> str:
    value = str(voice or "").strip()
    value = LEGACY_VOICE_ALIASES.get(value, value)
    if value not in VOICE_PROFILES:
        return DEFAULT_VOICE_PROFILE
    return value


def voice_profile(voice: str | None) -> dict[str, Any]:
    return VOICE_PROFILES[normalize_voice_profile(voice)]


def normalize_cloud_voice(voice: str | None) -> str:
    value = str(voice or "").strip()
    if value not in CLOUD_SYSTEM_VOICES:
        return DEFAULT_CLOUD_VOICE
    return value


def public_local_voice_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "description": profile["description"],
            "gender": profile.get("gender", ""),
            "style": profile.get("style", ""),
            "local_ready": Path(profile["local_reference_audio"]).is_file(),
            "license": profile.get("license", ""),
        }
        for profile in VOICE_PROFILES.values()
    ]


def public_cloud_voice_catalog() -> list[dict[str, str]]:
    return list(CLOUD_SYSTEM_VOICES.values())


def public_voice_catalog() -> list[dict[str, Any]]:
    """Compatibility alias for clients that previously listed one catalog."""
    return public_local_voice_catalog()
