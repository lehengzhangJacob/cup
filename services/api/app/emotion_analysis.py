from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import (
    EMOTION_BASE_MODEL_PATH,
    EMOTION_BERT_PATH,
    EMOTION_GPU,
    EMOTION_INFERENCE_SCRIPT,
    EMOTION_INFERENCE_URL,
    EMOTION_MODEL_PATH,
    EMOTION_PYTHON,
    EMOTION_TIMEOUT_SECONDS,
)


EMOTION_LABELS = (
    "angry",
    "disgust",
    "fear",
    "happy",
    "neutral",
    "sad",
    "surprise",
)

EMOTION_ALIASES = {
    "anger": "angry",
    "angry": "angry",
    "愤怒": "angry",
    "生气": "angry",
    "disgust": "disgust",
    "disgusted": "disgust",
    "厌恶": "disgust",
    "反感": "disgust",
    "fear": "fear",
    "fearful": "fear",
    "scared": "fear",
    "恐惧": "fear",
    "害怕": "fear",
    "happy": "happy",
    "happiness": "happy",
    "joy": "happy",
    "开心": "happy",
    "高兴": "happy",
    "neutral": "neutral",
    "calm": "neutral",
    "中性": "neutral",
    "平静": "neutral",
    "sad": "sad",
    "sadness": "sad",
    "悲伤": "sad",
    "难过": "sad",
    "surprise": "surprise",
    "surprised": "surprise",
    "惊讶": "surprise",
    "惊喜": "surprise",
}

ASPECT_KEYWORDS = {
    "讲解内容": ("讲解", "介绍", "历史", "文化", "内容", "故事"),
    "回答准确性": ("错误", "不对", "准确", "答非所问", "不知道", "编造"),
    "响应速度": ("慢", "延迟", "卡", "等待", "没反应", "响应"),
    "数字人体验": ("数字人", "表情", "口型", "声音", "语音", "形象"),
    "路线推荐": ("路线", "导航", "怎么走", "推荐", "行程", "下一站"),
    "排队与客流": ("排队", "拥挤", "人多", "客流", "等候"),
    "门票价格": ("门票", "票价", "价格", "贵", "收费"),
    "餐饮服务": ("餐饮", "吃饭", "餐厅", "素斋", "食物", "饮料"),
    "交通停车": ("交通", "停车", "公交", "打车", "接驳"),
    "现场服务": ("工作人员", "服务", "投诉", "态度", "卫生", "厕所"),
}

POSITIVE_WORDS = {
    "喜欢": 1.0,
    "满意": 1.0,
    "很好": 1.0,
    "不错": 0.8,
    "漂亮": 0.7,
    "方便": 0.7,
    "感谢": 0.6,
    "推荐": 0.7,
    "开心": 0.8,
    "震撼": 0.8,
    "清楚": 0.6,
    "准确": 0.8,
    "流畅": 0.8,
    "有趣": 0.7,
}

NEGATIVE_WORDS = {
    "不满意": 1.5,
    "不满": 1.0,
    "不准确": 1.2,
    "不推荐": 0.9,
    "不方便": 0.8,
    "不清楚": 0.8,
    "失望": 1.0,
    "不好": 0.8,
    "太慢": 1.0,
    "拥挤": 0.8,
    "排队": 0.5,
    "投诉": 1.0,
    "贵": 0.7,
    "累": 0.5,
    "生气": 1.0,
    "错误": 1.0,
    "答非所问": 1.0,
    "卡顿": 0.9,
    "没反应": 1.0,
    "听不清": 0.8,
}

NEGATION_PREFIXES = ("不", "没", "未", "无", "不太", "不够")


def normalize_emotion_label(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "", text)
    return EMOTION_ALIASES.get(text)


def analyze_text(text: str, rating: Optional[int] = None) -> dict[str, Any]:
    clean = (text or "").strip()
    positive_hits = [
        word
        for word in POSITIVE_WORDS
        if word in clean
        and not any(f"{prefix}{word}" in clean for prefix in NEGATION_PREFIXES)
    ]
    negative_hits = [word for word in NEGATIVE_WORDS if word in clean]
    positive = sum(POSITIVE_WORDS[word] for word in positive_hits)
    negative = sum(NEGATIVE_WORDS[word] for word in negative_hits)
    evidence = [*positive_hits, *negative_hits][:8]

    text_score = 0.0
    if positive or negative:
        text_score = (positive - negative) / max(positive + negative, 1.0)

    score = text_score
    text_has_signal = bool(positive_hits or negative_hits)
    sources = 1 if text_has_signal else 0
    if rating is not None:
        rating_score = max(-1.0, min(1.0, (rating - 3) / 2))
        score = (text_score * sources + rating_score * 1.5) / (sources + 1.5)
        sources += 1

    if score > 0.2:
        sentiment = "positive"
    elif score < -0.2:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    aspects = []
    for name, keywords in ASPECT_KEYWORDS.items():
        hits = [word for word in keywords if word in clean]
        if hits:
            aspects.append(
                {
                    "name": name,
                    "sentiment": sentiment,
                    "keywords": hits[:4],
                }
            )

    lexical_hits = len(evidence)
    confidence = 0.0
    if text_has_signal:
        confidence = 0.45 + lexical_hits * 0.07
    if rating is not None:
        confidence = max(confidence, 0.75) if not text_has_signal else confidence + 0.2
    confidence = min(0.95, confidence)
    return {
        "sentiment": sentiment,
        "valence": round(score, 4),
        "confidence": round(confidence, 4),
        "aspects": aspects,
        "evidence": evidence,
    }


def parse_model_output(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        raw_label = (
            payload.get("emotion")
            or payload.get("label")
            or payload.get("answer")
            or payload.get("prediction")
        )
        scores = payload.get("scores") or payload.get("probabilities") or {}
        normalized_scores: dict[str, float] = {}
        if isinstance(scores, dict):
            for key, value in scores.items():
                label = normalize_emotion_label(key)
                if label and isinstance(value, (int, float)):
                    normalized_scores[label] = round(float(value), 6)
        label = normalize_emotion_label(raw_label)
        if not label and normalized_scores:
            label = max(normalized_scores, key=normalized_scores.get)
        if not label:
            raise ValueError("情绪模型返回中没有可识别的七分类标签")
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = normalized_scores.get(label or "", 0.0)
        return {
            "emotion": label,
            "scores": normalized_scores,
            "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
            "model": str(payload.get("model") or ""),
        }

    text = str(payload or "").strip()
    if not text:
        raise ValueError("情绪模型没有返回结果")
    try:
        return parse_model_output(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        pass
    for line in reversed(text.splitlines()):
        try:
            return parse_model_output(json.loads(line.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
    for candidate in reversed(re.findall(r"\{[^{}]+\}", text, flags=re.S)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        result = parse_model_output(parsed)
        if result.get("emotion"):
            return result

    answer = re.findall(r"<answer>\s*([^<]+)\s*</answer>", text, flags=re.I)
    raw_label = answer[-1] if answer else text.splitlines()[-1]
    label = normalize_emotion_label(raw_label)
    if not label:
        for token in re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]+", raw_label):
            label = normalize_emotion_label(token)
            if label:
                break
    if not label:
        raise ValueError("无法从模型输出解析七分类情绪")
    return {
        "emotion": label,
        "scores": {},
        "confidence": 0.0,
        "model": "",
    }


def fuse_analysis(
    text_result: dict[str, Any],
    model_result: Optional[dict[str, Any]],
    rating: Optional[int] = None,
) -> dict[str, Any]:
    weighted: list[tuple[float, float]] = []
    text_confidence = float(text_result.get("confidence") or 0.0)
    if text_confidence:
        weighted.append((float(text_result.get("valence") or 0.0), 0.30 * text_confidence))
    if rating is not None:
        weighted.append((max(-1.0, min(1.0, (rating - 3) / 2)), 0.45))

    emotion_label = None
    emotion_confidence = 0.0
    if model_result:
        emotion_label = normalize_emotion_label(model_result.get("emotion"))
        emotion_confidence = float(model_result.get("confidence") or 0.0)
        emotion_valence = {
            "happy": 1.0,
            "angry": -1.0,
            "disgust": -0.9,
            "sad": -0.75,
            # Fear and surprise are deliberately ambiguous in a scenic area.
            "fear": 0.0,
            "surprise": 0.0,
            "neutral": 0.0,
        }.get(emotion_label or "", 0.0)
        if emotion_confidence:
            weighted.append((emotion_valence, 0.25 * emotion_confidence))

    total_weight = sum(weight for _, weight in weighted)
    valence = (
        sum(value * weight for value, weight in weighted) / total_weight
        if total_weight
        else 0.0
    )
    if valence > 0.2:
        sentiment = "positive"
    elif valence < -0.2:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    estimated = max(1.0, min(5.0, 3.0 + 2.0 * valence))
    return {
        "emotion": emotion_label,
        "sentiment": sentiment,
        "valence": round(valence, 4),
        "confidence": round(
            min(1.0, total_weight / 0.75 if total_weight else 0.0),
            4,
        ),
        "estimated_satisfaction": round(float(rating or estimated), 2),
        "observed_rating": rating,
        "aspects": text_result.get("aspects") or [],
        "evidence": text_result.get("evidence") or [],
        "emotion_confidence": round(emotion_confidence, 4),
    }


class EmotionAnalyzer:
    model_name = EMOTION_MODEL_PATH.name
    prompt = (
        "As an emotion recognition expert, analyze the person's facial "
        "expression and voice throughout this tourist interaction. Return "
        "exactly one label from angry, disgust, fear, happy, neutral, sad, "
        "surprise inside <answer></answer> tags."
    )

    def __init__(self) -> None:
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        self._local_lock = asyncio.Lock()

    def status(self, refresh: bool = False) -> dict[str, Any]:
        if EMOTION_INFERENCE_URL:
            return {
                "ready": True,
                "mode": "http",
                "model": EMOTION_MODEL_PATH.name,
                "endpoint": EMOTION_INFERENCE_URL,
                "checkpoint_exists": EMOTION_MODEL_PATH.exists(),
                "script_exists": EMOTION_INFERENCE_SCRIPT.exists(),
            }
        cached = self._status_cache
        if not refresh and cached and time.monotonic() - cached[0] < 30:
            return dict(cached[1])
        reasons = []
        if not EMOTION_MODEL_PATH.exists():
            reasons.append(f"模型目录不存在：{EMOTION_MODEL_PATH}")
        if not EMOTION_BASE_MODEL_PATH.exists():
            reasons.append(f"基础模型目录不存在：{EMOTION_BASE_MODEL_PATH}")
        if not EMOTION_BERT_PATH.exists():
            reasons.append(f"BERT 目录不存在：{EMOTION_BERT_PATH}")
        if not EMOTION_INFERENCE_SCRIPT.exists():
            reasons.append(f"推理脚本不存在：{EMOTION_INFERENCE_SCRIPT}")
        python_path = shutil.which(EMOTION_PYTHON)
        if not python_path:
            reasons.append(f"推理 Python 不存在：{EMOTION_PYTHON}")
        if python_path:
            try:
                check = subprocess.run(
                    [
                        EMOTION_PYTHON,
                        "-c",
                        "from humanomni import model_init, mm_infer, "
                        "emotion_probs_from_logits; import peft, torch",
                    ],
                    cwd=str(EMOTION_INFERENCE_SCRIPT.parent),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if check.returncode != 0:
                    detail = (check.stderr or check.stdout).strip().splitlines()
                    reasons.append(
                        "推理环境缺少训练版 humanomni 七分类扩展/peft："
                        + (detail[-1][:300] if detail else "import failed")
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                reasons.append(f"推理环境检查失败：{exc}")
        result = {
            "ready": not reasons,
            "mode": "local-script",
            "model": EMOTION_MODEL_PATH.name,
            "model_path": str(EMOTION_MODEL_PATH),
            "base_model_path": str(EMOTION_BASE_MODEL_PATH),
            "bert_path": str(EMOTION_BERT_PATH),
            "script_path": str(EMOTION_INFERENCE_SCRIPT),
            "python": python_path or EMOTION_PYTHON,
            "checkpoint_exists": EMOTION_MODEL_PATH.exists(),
            "base_model_exists": EMOTION_BASE_MODEL_PATH.exists(),
            "script_exists": EMOTION_INFERENCE_SCRIPT.exists(),
            "gpu": EMOTION_GPU,
            "detail": "；".join(reasons)
            if reasons
            else "HumanOmni 训练版七分类音视频推理已配置",
        }
        self._status_cache = (time.monotonic(), dict(result))
        return result

    async def _call_http(
        self,
        media_path: Path,
        transcript: str,
        context_turns: list[dict[str, str]],
    ) -> dict[str, Any]:
        raw = await asyncio.to_thread(media_path.read_bytes)
        async with httpx.AsyncClient(timeout=EMOTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                EMOTION_INFERENCE_URL,
                data={
                    "transcript": transcript,
                    "prompt": self.prompt,
                    "context_json": json.dumps(context_turns, ensure_ascii=False),
                },
                files={
                    "file": (
                        media_path.name,
                        raw,
                        "video/mp4" if media_path.suffix.lower() == ".mp4" else "video/webm",
                    )
                },
            )
            response.raise_for_status()
            return parse_model_output(response.json())

    async def _call_local(
        self,
        media_path: Path,
        transcript: str,
        context_turns: list[dict[str, str]],
    ) -> dict[str, Any]:
        env = os.environ.copy()
        if EMOTION_GPU:
            env["CUDA_VISIBLE_DEVICES"] = EMOTION_GPU
        command = [
            EMOTION_PYTHON,
            str(EMOTION_INFERENCE_SCRIPT),
            "--base-model-path",
            str(EMOTION_BASE_MODEL_PATH),
            "--emotion-lora",
            str(EMOTION_MODEL_PATH),
            "--bert-path",
            str(EMOTION_BERT_PATH),
            "--text",
            transcript,
            "--context-json",
            json.dumps(context_turns[-6:], ensure_ascii=False),
        ]
        if media_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            command.extend(["--audio-path", str(media_path)])
        else:
            command.extend(["--video-path", str(media_path)])
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(EMOTION_INFERENCE_SCRIPT.parent),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=EMOTION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError("多模态情绪模型推理超时")
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-800:]
            raise RuntimeError(f"多模态情绪模型推理失败：{detail}")
        result = parse_model_output(stdout.decode("utf-8", errors="replace"))
        result["model"] = result.get("model") or EMOTION_MODEL_PATH.name
        return result

    async def analyze(
        self,
        media_path: Optional[Path],
        transcript: str,
        rating: Optional[int] = None,
        context_turns: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        # Keep the explicit 1–5 score as its own fusion source instead of
        # counting it once in text analysis and a second time below.
        text_result = analyze_text(transcript)
        model_result: Optional[dict[str, Any]] = None
        model_error = ""
        status = self.status() if media_path else {"ready": False}
        if media_path and status["ready"]:
            try:
                model_result = (
                    await self._call_http(media_path, transcript, context_turns or [])
                    if EMOTION_INFERENCE_URL
                    else await self._call_local_serialized(
                        media_path,
                        transcript,
                        context_turns or [],
                    )
                )
            except Exception as exc:
                model_error = str(exc)
        elif media_path:
            model_error = str(status.get("detail") or "多模态模型未配置")

        fused = fuse_analysis(text_result, model_result, rating)
        if model_result and media_path:
            analysis_mode = (
                "audio-text"
                if media_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
                else "video-text"
            )
        elif media_path:
            analysis_mode = "text-fallback"
        else:
            analysis_mode = "text"
        fused.update(
            {
                "scores": (model_result or {}).get("scores") or {},
                "model": (model_result or {}).get("model") or EMOTION_MODEL_PATH.name,
                "analysis_mode": analysis_mode,
                "model_error": model_error,
            }
        )
        return fused

    async def _call_local_serialized(
        self,
        media_path: Path,
        transcript: str,
        context_turns: list[dict[str, str]],
    ) -> dict[str, Any]:
        async with self._local_lock:
            return await self._call_local(media_path, transcript, context_turns)


emotion_analyzer = EmotionAnalyzer()
