# tests/eval_accuracy.py
"""
手动运行：python tests/eval_accuracy.py
输出每题结果和总准确率。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.pipeline import RAGPipeline

TEST_CASES = [
    # (问题, 回答中必须包含的关键词列表，命中任一即算通过)
    ("灵山大佛是用什么材料建造的？",          ["青铜", "铜"]),
    ("灵山大佛有多高？",                      ["88"]),
    ("九龙灌浴代表什么含义？",                ["释迦牟尼", "诞生"]),
    ("灵山梵宫被称为什么？",                  ["卢浮宫"]),
    ("五印坛城是什么风格的建筑？",            ["藏传"]),
    ("祥符禅寺有多少年历史？",                ["千年", "1008", "宋"]),
    ("亲子家庭游览路线怎么走？",              ["九龙灌浴", "百子戏弥勒", "佛手"]),
    ("历史文化爱好者推荐什么路线？",          ["祥符禅寺", "灵山大佛", "梵宫"]),
    ("景区最佳游览季节是什么时候？",          ["春", "秋"]),
    ("九龙灌浴每天有几场表演？",              ["4", "5", "场"]),
    ("灵山精舍提供什么体验？",                ["素斋", "早课", "禅"]),
    ("菩提大道有什么特色？",                  ["太湖", "菩提"]),
    ("灵山梵宫的穹顶有什么？",                ["天象", "飞天", "壁画", "星空", "星辰", "苍穹", "LED", "日月"]),
    ("如何抱佛脚？",                          ["灵山大佛", "台阶", "祈福", "佛脚"]),
    ("曼飞龙塔是什么风格？",                  ["傣族"]),
]


def main():
    pipeline = RAGPipeline()
    passed = 0
    for question, keywords in TEST_CASES:
        answer = pipeline.query(question)
        hit = any(kw in answer for kw in keywords)
        status = "PASS" if hit else "FAIL"
        if hit:
            passed += 1
        print(f"[{status}] 问：{question}")
        print(f"       答：{answer}")
        if not hit:
            print(f"       期望包含: {keywords}")
        print()
    total = len(TEST_CASES)
    accuracy = passed / total * 100
    print(f"准确率: {passed}/{total} = {accuracy:.1f}%")
    assert accuracy >= 90, f"准确率 {accuracy:.1f}% 低于90%要求"


if __name__ == "__main__":
    main()
