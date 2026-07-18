# rag/prompt_builder.py

SYSTEM_PROMPT = (
    "你是灵山胜境的AI导游，名叫灵灵。请只根据下方提供的景区资料回答游客问题，"
    "不要编造资料中没有的内容。回答要自然亲切，适合口语表达。"
)


def build_prompt(chunks: list, question: str) -> tuple:
    """返回 (system_prompt, user_message)。"""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk["metadata"]
        name = meta.get("attraction_name", "")
        area = meta.get("scenic_area", "")
        section = meta.get("section", "")
        # 子景点标注所属景区，帮助模型理解层级
        head = f"{area}·{name}" if area and area != name else name
        label = f"[资料{i}] {head} - {section}" if section else f"[资料{i}] {head}"
        context_parts.append(f"{label}\n{chunk['text']}")

    context = "\n\n".join(context_parts)
    user_message = f"参考资料：\n{context}\n\n游客问题：{question}"
    return SYSTEM_PROMPT, user_message
