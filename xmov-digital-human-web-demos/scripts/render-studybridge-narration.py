from __future__ import annotations

import json
import subprocess
from pathlib import Path


VOICE = "Microsoft Huihui Desktop"
INITIAL_SILENCE = 3.0
INTER_SEGMENT_GAP = 2.0
ENDING_SILENCE = 3.0


def build_speech(country: str, degree: str, major: str, budget: str) -> str:
    return (
        f"你好，根据你想申请{country}{degree}的{major}方向，我建议先把申请定位做清楚。"
        f"结合{budget}预算和你当前的背景，更适合采用冲刺、主申、保稳三层选校策略，"
        "再优先补强文书、简历和能证明方向匹配的经历，这样申请会更稳。"
    )


SEGMENTS = [
    {
        "name": "intro",
        "text": "欢迎进入留学申请咨询台。本次会根据目标国家、专业方向和预算，整理申请定位、选校建议和准备节奏。",
    },
    {
        "name": "us_ai",
        "text": build_speech("美国", "硕士", "人工智能 / 计算机", "60 万人民币以上"),
    },
    {
        "name": "uk_finance",
        "text": build_speech("英国", "硕士", "金融 / 金融科技", "40-60 万人民币"),
    },
    {
        "name": "hk_media",
        "text": build_speech("香港", "硕士", "传媒 / 新媒体", "30-40 万人民币"),
    },
]


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return float(result.stdout.strip())


def synthesize_with_windows_tts(text: str, output_path: Path) -> None:
    safe_text = text.replace("'", "''")
    safe_path = str(output_path).replace("'", "''")
    safe_voice = VOICE.replace("'", "''")
    command = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('{safe_voice}')
$synth.Rate = -1
$synth.SetOutputToWaveFile('{safe_path}')
$synth.Speak('{safe_text}')
$synth.Dispose()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
    )


def synthesize_segments(audio_dir: Path) -> list[dict]:
    rendered = []
    for segment in SEGMENTS:
        output_path = audio_dir / f"{segment['name']}.wav"
        synthesize_with_windows_tts(segment["text"], output_path)
        rendered.append(
            {
                **segment,
                "file": str(output_path),
                "duration": ffprobe_duration(output_path),
            }
        )
    return rendered


def mix_audio(rendered_segments: list[dict], output_path: Path) -> tuple[list[dict], float]:
    starts = []
    current = INITIAL_SILENCE
    for segment in rendered_segments:
        starts.append(current)
        current += segment["duration"] + INTER_SEGMENT_GAP

    total_duration = current - INTER_SEGMENT_GAP + ENDING_SILENCE

    cmd = ["ffmpeg", "-y"]
    for segment in rendered_segments:
        cmd.extend(["-i", segment["file"]])

    filter_parts = []
    for index, (segment, start) in enumerate(zip(rendered_segments, starts)):
        delay = int(round(start * 1000))
        filter_parts.append(f"[{index}:a]adelay={delay}|{delay}[a{index}]")

    mixed_inputs = "".join(f"[a{index}]" for index in range(len(rendered_segments)))
    filter_parts.append(f"{mixed_inputs}amix=inputs={len(rendered_segments)}:normalize=0:duration=longest[aout]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[aout]",
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            "mp3",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )

    subprocess.run(cmd, check=True)

    manifest_segments = []
    for segment, start in zip(rendered_segments, starts):
        manifest_segments.append(
            {
                "name": segment["name"],
                "text": segment["text"],
                "file": segment["file"],
                "duration": round(segment["duration"], 3),
                "start": round(start, 3),
            }
        )

    return manifest_segments, round(total_duration, 3)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    work_dir = root / "output" / "video-work"
    audio_dir = work_dir / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    rendered = synthesize_segments(audio_dir)
    mixed_audio_path = work_dir / "studybridge-narration.mp3"
    manifest_segments, total_duration = mix_audio(rendered, mixed_audio_path)

    manifest = {
        "voice": VOICE,
        "audio_path": str(mixed_audio_path),
        "initial_silence": INITIAL_SILENCE,
        "inter_segment_gap": INTER_SEGMENT_GAP,
        "ending_silence": ENDING_SILENCE,
        "total_duration": total_duration,
        "segments": manifest_segments,
    }

    manifest_path = work_dir / "studybridge-narration-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(manifest_path)
    print(mixed_audio_path)


if __name__ == "__main__":
    main()
