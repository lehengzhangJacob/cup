"""Evaluate factual QA accuracy against the running scenic-guide API.

Usage:
    python scripts/eval_accuracy.py [http://127.0.0.1:8001]
"""

from __future__ import annotations

import sys

import httpx


TEST_CASES = [
    ("灵山大佛是用什么材料建造的？", ["青铜", "铜"]),
    ("灵山大佛有多高？", ["88"]),
    ("九龙灌浴代表什么含义？", ["释迦牟尼", "诞生"]),
    ("灵山梵宫被称为什么？", ["卢浮宫"]),
    ("五印坛城是什么风格的建筑？", ["藏传", "藏式"]),
    ("祥符禅寺有多少年历史？", ["千年", "1008", "宋"]),
    ("亲子家庭游览路线怎么走？", ["九龙灌浴", "百子戏弥勒", "佛手"]),
    ("历史文化爱好者推荐什么路线？", ["祥符禅寺", "灵山大佛", "梵宫"]),
    ("景区最佳游览季节是什么时候？", ["春", "秋"]),
    ("九龙灌浴每天有几场表演？", ["4", "5", "场"]),
    ("灵山精舍提供什么体验？", ["素斋", "早课", "禅"]),
    ("菩提大道有什么特色？", ["太湖", "菩提"]),
    ("灵山梵宫的穹顶有什么？", ["天象", "飞天", "壁画", "星空", "星辰", "苍穹", "LED", "日月"]),
    ("如何抱佛脚？", ["灵山大佛", "台阶", "祈福", "佛脚"]),
    ("曼飞龙塔是什么风格？", ["傣族"]),
]


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")
    passed = 0
    with httpx.Client(timeout=45, trust_env=False) as client:
        for index, (question, keywords) in enumerate(TEST_CASES, 1):
            response = client.post(
                f"{base_url}/v1/chat",
                json={"message": question, "interest": "历史", "stream": False},
            )
            response.raise_for_status()
            answer = response.json()["answer"]
            hit = any(keyword in answer for keyword in keywords)
            passed += int(hit)
            print(f"[{index:02d}] {'PASS' if hit else 'FAIL'} {question}")
            if not hit:
                print(f"     expected one of {keywords}; answer={answer!r}")
    accuracy = passed / len(TEST_CASES) * 100
    print(f"accuracy: {passed}/{len(TEST_CASES)} = {accuracy:.1f}%")
    return 0 if accuracy >= 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
