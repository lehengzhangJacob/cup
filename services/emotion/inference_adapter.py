#!/usr/bin/env python3
"""CLI adapter for the team's HumanOmni seven-class emotion LoRA.

This wrapper intentionally loads only the emotion adapter. It accepts the
visitor's ASR text, optional audio/video, and recent dialogue context, then
prints one machine-readable JSON object as its final stdout line.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

import torch


LABELS = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")
ALIASES = {
    "anger": "angry", "angry": "angry", "愤怒": "angry", "生气": "angry",
    "disgust": "disgust", "disgusted": "disgust", "厌恶": "disgust",
    "fear": "fear", "fearful": "fear", "恐惧": "fear", "害怕": "fear",
    "happy": "happy", "happiness": "happy", "joy": "happy", "开心": "happy",
    "neutral": "neutral", "calm": "neutral", "中性": "neutral", "平静": "neutral",
    "sad": "sad", "sadness": "sad", "悲伤": "sad", "难过": "sad",
    "surprise": "surprise", "surprised": "surprise", "惊讶": "surprise",
}


def normalize_label(value: Any) -> str | None:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "", str(value or "").strip().lower())
    return ALIASES.get(text)


def plain(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach().float().cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalize_scores(value: Any) -> dict[str, float]:
    # Generation scores are a tuple of full-vocabulary tensors, one per
    # generated token. They are not seven-class probabilities and converting
    # them to Python lists would allocate hundreds of thousands of floats.
    if isinstance(value, (list, tuple)) and value and all(
        hasattr(item, "shape") for item in value
    ):
        return {}
    value = plain(value)
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    result: dict[str, float] = {}
    if isinstance(value, dict):
        for key, score in value.items():
            label = normalize_label(key)
            if label and isinstance(score, (int, float)):
                result[label] = float(score)
    elif isinstance(value, list) and len(value) == len(LABELS):
        for label, score in zip(LABELS, value):
            if isinstance(score, (int, float)):
                result[label] = float(score)
    total = sum(max(0.0, score) for score in result.values())
    if total > 0 and not 0.98 <= total <= 1.02:
        result = {key: max(0.0, score) / total for key, score in result.items()}
    return {key: round(score, 6) for key, score in result.items()}


def output_label(text: Any) -> str | None:
    answer = re.findall(r"<answer>\s*([^<]+)\s*</answer>", str(text or ""), flags=re.I)
    candidates = [answer[-1]] if answer else []
    candidates.extend(re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]+", str(text or "")))
    for candidate in reversed(candidates):
        label = normalize_label(candidate)
        if label:
            return label
    return None


def seven_class_scores_from_generation(
    output_text: Any,
    generation_scores: Any,
    tokenizer: Any,
) -> dict[str, float]:
    """Read a seven-class distribution from the generation step of its label.

    The training fork exposes full-vocabulary logits for each generated token.
    Its separate emotion_probs_from_logits helper remains a three-way
    sentiment output, so it must not be written into the seven-class column.
    """
    if not isinstance(generation_scores, (list, tuple)) or not generation_scores:
        return {}
    try:
        generated_ids = tokenizer.encode(
            str(output_text or ""),
            add_special_tokens=False,
        )
    except Exception:
        return {}
    if not generated_ids:
        return {}

    forms = {
        "angry": (" angry", " anger", "angry", "anger"),
        "disgust": (" disgust", "disgust"),
        "fear": (" fear", "fear"),
        "happy": (" happy", " joy", "happy", "joy"),
        "neutral": (" neutral", "neutral"),
        "sad": (" sad", " sadness", "sad", "sadness"),
        "surprise": (" surprise", "surprise"),
    }
    token_to_label: dict[int, str] = {}
    label_tokens: dict[str, list[int]] = {}
    for label, candidates in forms.items():
        ids: list[int] = []
        for candidate in candidates:
            ids_for_candidate = tokenizer.encode(candidate, add_special_tokens=False)
            if len(ids_for_candidate) == 1:
                token_id = int(ids_for_candidate[0])
                if token_id not in ids:
                    ids.append(token_id)
                    token_to_label[token_id] = label
        if ids:
            label_tokens[label] = ids
    if len(label_tokens) != len(LABELS):
        return {}

    # Select the last emitted seven-class label, e.g. the joy in
    # positive, joy after the training prompt asks for both taxonomies.
    selected_step = None
    for index, token_id in enumerate(generated_ids):
        if token_id in token_to_label and index < len(generation_scores):
            selected_step = index
    if selected_step is None:
        return {}
    step_logits = generation_scores[selected_step]
    if not isinstance(step_logits, torch.Tensor) or step_logits.ndim != 2:
        return {}

    all_token_ids = [token_id for ids in label_tokens.values() for token_id in ids]
    selected_logits = step_logits[0, all_token_ids]
    selected_probs = torch.softmax(selected_logits.float(), dim=-1).detach().cpu().tolist()
    by_token = dict(zip(all_token_ids, selected_probs))
    result = {
        label: sum(by_token[token_id] for token_id in ids)
        for label, ids in label_tokens.items()
    }
    total = sum(result.values())
    if total <= 0:
        return {}
    return {label: round(value / total, 6) for label, value in result.items()}


def make_prompt(modal: str, text: str, context_turns: list[dict[str, str]]) -> str:
    lines = ["[Current Turn]"]
    if "video" in modal:
        lines.extend(["Video:", "<video>"])
    if "audio" in modal:
        lines.extend(["Audio:", "<audio>"])
    lines.extend(["Speaker: tourist", f'Text: "{text}"', "", "[Context]"])
    if context_turns:
        for index, turn in enumerate(context_turns[-6:], start=1):
            speaker = str(turn.get("speaker") or "unknown")[:30]
            content = str(turn.get("text") or "")[:1000]
            lines.append(f'Turn -{len(context_turns[-6:]) - index + 1}: Speaker {speaker}: "{content}"')
    else:
        lines.append("No previous context available.")
    lines.extend(
        [
            "",
            "Instruction:",
            "As an emotion recognition expert, analyze the emotion of the Current Turn's "
            "speaker. Your analysis MUST be based on:",
            "1. The speaker's own textual and audio cues in the Current Turn (no facial "
            "video is available; do not infer from visual/face cues).",
            "2. The historical context of the conversation provided.",
            "3. The speaker's identity and their interaction with others in the Context.",
            "Please output the results of emotion three classification and emotion seven "
            "classification.",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model-path", required=True)
    parser.add_argument("--emotion-lora", required=True)
    parser.add_argument("--bert-path", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--audio-path")
    parser.add_argument("--video-path")
    parser.add_argument("--context-json", default="[]")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # HumanOmni's upstream architecture uses a model name while constructing
    # the embedded BERT gate. Point it at the deployment's local checkpoint
    # before importing the package so inference remains fully offline.
    os.environ["HUMANOMNI_BERT_PATH"] = args.bert_path
    import humanomni
    from humanomni.utils import disable_torch_init
    from peft import PeftModel
    from transformers import BertTokenizer

    model_init = humanomni.model_init
    mm_infer = humanomni.mm_infer
    emotion_probs_from_logits = getattr(
        humanomni,
        "emotion_probs_from_logits",
        None,
    )
    if emotion_probs_from_logits is None:
        raise RuntimeError(
            "The training-time HumanOmni extension emotion_probs_from_logits "
            "is required for seven-class inference."
        )

    try:
        context = json.loads(args.context_json)
    except json.JSONDecodeError:
        context = []
    if not isinstance(context, list):
        context = []

    if args.video_path and args.audio_path:
        modal = "video_audio"
    elif args.video_path:
        modal = "video"
    elif args.audio_path:
        modal = "audio"
    else:
        modal = "text"

    bert_tokenizer = BertTokenizer.from_pretrained(args.bert_path, local_files_only=True)
    disable_torch_init()
    model, processor, tokenizer = model_init(
        args.base_model_path,
        skip_vision=not bool(args.video_path),
    )
    model = PeftModel.from_pretrained(
        model,
        args.emotion_lora,
        adapter_name="emotion",
        local_files_only=True,
    )
    model.set_adapter("emotion")
    model.eval()

    video_tensor = processor["video"](args.video_path) if args.video_path else None
    audio_tensor = processor["audio"](args.audio_path)[0] if args.audio_path else None
    prompt = make_prompt(modal, args.text, context)
    raw = mm_infer(
        video_tensor,
        prompt,
        model=model,
        tokenizer=tokenizer,
        modal=modal,
        question=prompt,
        bert_tokeni=bert_tokenizer,
        do_sample=False,
        audio=audio_tensor,
    )
    if isinstance(raw, tuple):
        emotion_output = raw[0] if raw else ""
        logits = raw[1] if len(raw) > 1 else None
        model_scores = raw[2] if len(raw) > 2 else None
    else:
        emotion_output, logits, model_scores = raw, None, None

    scores = seven_class_scores_from_generation(
        emotion_output,
        model_scores,
        tokenizer,
    )
    if not scores and isinstance(model_scores, dict):
        scores = normalize_scores(model_scores)

    sentiment_scores = {}
    if logits is not None:
        try:
            raw_sentiment_scores = emotion_probs_from_logits(logits)
            if isinstance(raw_sentiment_scores, list) and raw_sentiment_scores:
                raw_sentiment_scores = raw_sentiment_scores[0]
            if isinstance(raw_sentiment_scores, dict):
                sentiment_scores = {
                    str(key): round(float(value), 6)
                    for key, value in raw_sentiment_scores.items()
                    if isinstance(value, (int, float))
                }
        except Exception:
            sentiment_scores = {}
    label = output_label(emotion_output)
    if not label and scores:
        label = max(scores, key=scores.get)
    if not label:
        raise RuntimeError(f"Cannot parse seven-class emotion from output: {emotion_output!r}")
    print(
        json.dumps(
            {
                "emotion": label,
                "scores": scores,
                "confidence": scores.get(label, 0.0),
                "model": "emotion_v5_stage2",
                "raw_output": str(emotion_output)[:500],
                "sentiment_scores": sentiment_scores,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
