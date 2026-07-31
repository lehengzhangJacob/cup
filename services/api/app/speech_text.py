from __future__ import annotations

from opencc import OpenCC


_OPENCC = OpenCC("t2s")

DOMAIN_CORRECTIONS = {
    "泥山": "灵山",
    "尼山": "灵山",
    "林山": "灵山",
    "宁山": "灵山",
    "靈山": "灵山",
    "宁宁": "灵灵",
    "玲玲": "灵灵",
    "灵玲": "灵灵",
    "年花湾": "拈花湾",
    "粘花湾": "拈花湾",
    "拈花彎": "拈花湾",
    "梵工": "梵宫",
    "梵公": "梵宫",
    "無印壇城": "五印坛城",
    "无印坛城": "五印坛城",
}


def normalize_asr_text(text: str | None) -> str:
    """Apply one transcript contract to local FunASR and cloud GLM-ASR."""
    value = _OPENCC.convert(str(text or "").strip())
    for source, target in DOMAIN_CORRECTIONS.items():
        value = value.replace(source, target)
    return value
