from html import escape
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent / "diagrams"

INK = "#173D34"
ACCENT = "#B75538"
GOLD = "#C89B45"
PAPER = "#FBF8F0"
PALE_GREEN = "#E7F0EA"
PALE_RED = "#F8E9E3"
PALE_GOLD = "#F5EEDC"
MUTED = "#52645E"
GRID = "#B9C7C1"
WHITE = "#FFFFFF"


def svg_document(width: int, height: int, title: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">灵山小向导项目软件工程图</desc>
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{INK}"/></marker>
  <marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{ACCENT}"/></marker>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#173D34" flood-opacity="0.12"/></filter>
  <style>
    text {{ font-family: "Noto Sans CJK SC", "Noto Sans CJK JP", "Droid Sans Fallback", sans-serif; fill: {INK}; }}
    .title {{ font-family: "Noto Serif CJK SC", "AR PL UMing CN", serif; font-size: 38px; font-weight: 700; }}
    .subtitle {{ font-size: 18px; fill: {MUTED}; }}
    .label {{ font-size: 22px; font-weight: 700; }}
    .body {{ font-size: 19px; }}
    .small {{ font-size: 16px; fill: {MUTED}; }}
    .tiny {{ font-size: 14px; fill: {MUTED}; }}
    .mono {{ font-family: "DejaVu Sans Mono", monospace; font-size: 16px; }}
    .connector {{ stroke: {INK}; stroke-width: 2.5; fill: none; marker-end: url(#arrow); }}
    .association {{ stroke: {MUTED}; stroke-width: 2; fill: none; }}
    .dashed {{ stroke: {MUTED}; stroke-width: 2; stroke-dasharray: 9 8; fill: none; }}
  </style>
</defs>
<rect width="{width}" height="{height}" fill="{PAPER}"/>
{body}
</svg>'''


def text_line(x: float, y: float, value: str, css_class: str = "body", anchor: str = "start", fill: str | None = None) -> str:
    color = f' fill="{fill}"' if fill else ""
    return f'<text x="{x}" y="{y}" class="{css_class}" text-anchor="{anchor}"{color}>{escape(value)}</text>'


def multiline_text(x: float, y: float, lines: list[str], css_class: str = "body", anchor: str = "middle", line_height: int = 25) -> str:
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if index == 0 else line_height}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    return f'<text x="{x}" y="{y}" class="{css_class}" text-anchor="{anchor}">{spans}</text>'


def rounded_box(x: float, y: float, width: float, height: float, fill: str, stroke: str = GRID, radius: int = 18, shadow: bool = False) -> str:
    filter_attr = ' filter="url(#shadow)"' if shadow else ""
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"{filter_attr}/>'


def connector(x1: float, y1: float, x2: float, y2: float, dashed: bool = False, arrow: bool = True, accent: bool = False) -> str:
    stroke = ACCENT if accent else INK
    dash = ' stroke-dasharray="9 8"' if dashed else ""
    marker = ' marker-end="url(#arrow-accent)"' if accent and arrow else (' marker-end="url(#arrow)"' if arrow else "")
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="2.5"{dash}{marker}/>'


def polyline(points: list[tuple[float, float]], dashed: bool = False, arrow: bool = True, accent: bool = False) -> str:
    encoded = " ".join(f"{x},{y}" for x, y in points)
    stroke = ACCENT if accent else INK
    dash = ' stroke-dasharray="9 8"' if dashed else ""
    marker = ' marker-end="url(#arrow-accent)"' if accent and arrow else (' marker-end="url(#arrow)"' if arrow else "")
    return f'<polyline points="{encoded}" fill="none" stroke="{stroke}" stroke-width="2.5" stroke-linejoin="round"{dash}{marker}/>'


def actor(x: float, y: float, name: str) -> str:
    return "".join(
        [
            f'<circle cx="{x}" cy="{y}" r="24" fill="{WHITE}" stroke="{INK}" stroke-width="4"/>',
            f'<line x1="{x}" y1="{y + 24}" x2="{x}" y2="{y + 105}" stroke="{INK}" stroke-width="4"/>',
            f'<line x1="{x - 42}" y1="{y + 58}" x2="{x + 42}" y2="{y + 58}" stroke="{INK}" stroke-width="4"/>',
            f'<line x1="{x}" y1="{y + 105}" x2="{x - 38}" y2="{y + 155}" stroke="{INK}" stroke-width="4"/>',
            f'<line x1="{x}" y1="{y + 105}" x2="{x + 38}" y2="{y + 155}" stroke="{INK}" stroke-width="4"/>',
            text_line(x, y + 198, name, "label", "middle"),
        ]
    )


def use_case_ellipse(center_x: float, center_y: float, lines: list[str], fill: str) -> str:
    start_y = center_y + 7 - (len(lines) - 1) * 12
    return "".join(
        [
            f'<ellipse cx="{center_x}" cy="{center_y}" rx="178" ry="43" fill="{fill}" stroke="{INK}" stroke-width="2.5" filter="url(#shadow)"/>',
            multiline_text(center_x, start_y, lines, "body", "middle", 24),
        ]
    )


def build_use_case() -> str:
    width, height = 1450, 920
    items: list[str] = [
        text_line(65, 62, "系统用例图", "title"),
        text_line(65, 94, "游客服务与景区运营两类角色共享同一导览平台", "subtitle"),
        f'<rect x="225" y="120" width="1000" height="735" rx="24" fill="#FFFFFF" fill-opacity="0.64" stroke="{INK}" stroke-width="3"/>',
        text_line(725, 158, "灵山小向导·灵曦", "label", "middle"),
        f'<line x1="725" y1="180" x2="725" y2="825" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 9"/>',
        text_line(475, 205, "游客端服务", "small", "middle"),
        text_line(975, 205, "景区管理服务", "small", "middle"),
    ]
    visitor_cases = [
        ["文字 / 语音景区问答"],
        ["数字人语音、口型", "同步讲解"],
        ["获取个性化游览路线"],
        ["拍照识景并校准讲解"],
        ["GPS / 景点码 / 手动定位"],
        ["提交景点评分与建议"],
    ]
    admin_cases = [
        ["查看运营概览与热门咨询"],
        ["维护知识文档并重建索引"],
        ["配置数字人名称、形象和音色"],
        ["查看情绪与满意度报告"],
        ["分析历史游客并获得建议"],
    ]
    visitor_y = [270, 375, 480, 585, 690, 795]
    admin_y = [285, 410, 535, 660, 785]
    for center_y in visitor_y:
        items.append(connector(168, 430, 292, center_y, arrow=False))
    for center_y in admin_y:
        items.append(connector(1282, 430, 1158, center_y, arrow=False))
    items.append(actor(112, 320, "游客"))
    items.append(actor(1338, 320, "景区管理员"))
    for center_y, lines in zip(visitor_y, visitor_cases):
        items.append(use_case_ellipse(475, center_y, lines, PALE_GREEN))
    for center_y, lines in zip(admin_y, admin_cases):
        items.append(use_case_ellipse(975, center_y, lines, PALE_GOLD))
    return svg_document(width, height, "灵山小向导系统用例图", "\n".join(items))


def architecture_box(x: float, y: float, width: float, height: float, title: str, lines: list[str], fill: str) -> str:
    elements = [rounded_box(x, y, width, height, fill, shadow=True), text_line(x + width / 2, y + 38, title, "label", "middle")]
    elements.append(multiline_text(x + width / 2, y + 72, lines, "small", "middle", 24))
    return "".join(elements)


def build_architecture() -> str:
    width, height = 1450, 1050
    items: list[str] = [
        text_line(65, 62, "系统总体架构图", "title"),
        text_line(65, 94, "接入层、网关层、智能服务层与数据资产层分层解耦", "subtitle"),
    ]
    layer_specs = [
        (130, "接入层", PALE_GREEN),
        (320, "网关与业务层", PALE_GOLD),
        (525, "智能服务层", PALE_RED),
        (765, "数据与资源层", "#EDF1F3"),
    ]
    for top, label, fill in layer_specs:
        items.append(f'<rect x="55" y="{top}" width="1340" height="{155 if top < 525 else (190 if top == 525 else 210)}" rx="22" fill="{fill}" fill-opacity="0.46" stroke="{GRID}" stroke-width="1.5"/>')
        items.append(text_line(82, top + 34, label, "small"))
    items.extend(
        [
            polyline([(365, 250), (365, 350)], arrow=True),
            polyline([(1085, 250), (1085, 350)], arrow=True),
            polyline([(365, 465), (365, 505), (245, 505), (245, 560)], arrow=True),
            polyline([(365, 465), (365, 505), (565, 505), (565, 560)], arrow=True),
            polyline([(365, 465), (365, 505), (885, 505), (885, 560)], arrow=True),
            polyline([(1085, 465), (1085, 505), (885, 505), (885, 560)], arrow=True),
            polyline([(1085, 465), (1085, 505), (1205, 505), (1205, 560)], arrow=True),
            polyline([(245, 690), (245, 810)], arrow=True),
            polyline([(885, 690), (885, 810)], arrow=True),
            polyline([(1205, 690), (1205, 740), (885, 740), (885, 810)], arrow=True),
            polyline([(365, 465), (400, 465), (400, 750), (565, 750), (565, 810)], arrow=True),
            polyline([(1085, 465), (1050, 465), (1050, 750), (565, 750), (565, 810)], arrow=True),
            polyline([(1205, 810), (1345, 810), (1345, 505), (1085, 505)], arrow=True, dashed=True),
            architecture_box(160, 170, 410, 80, "游客浏览器 / Android App", ["文字 · 麦克风 · 图片 · 兴趣 · 位置"], WHITE),
            architecture_box(880, 170, 410, 80, "景区管理后台", ["知识库 · 数字人配置 · 数据 · 报告"], WHITE),
            architecture_box(160, 350, 410, 115, "FastAPI 导览网关", ["HTTPS / SSE / WebRTC 代理", "会话、路线、定位、反馈"], WHITE),
            architecture_box(880, 350, 410, 115, "管理服务与鉴权", ["签名 Cookie / 来源校验", "统计分析与配置管理"], WHITE),
            architecture_box(105, 560, 280, 130, "RAG 服务", ["BGE-M3 + FAISS", "GLM 流式问答与引用"], WHITE),
            architecture_box(425, 560, 280, 130, "GLM 多模态", ["ASR · 4V · TTS", "云端模型 API"], WHITE),
            architecture_box(745, 560, 280, 130, "LiveTalking", ["Wav2Lip FP16", "WebRTC 音视频"], WHITE),
            architecture_box(1065, 560, 280, 130, "HumanOmni", ["七类情绪与文本倾向", "异步分析 / 失败降级"], WHITE),
            architecture_box(105, 810, 280, 145, "知识资产", ["官方 / 管理员文档", "97 个片段 + 元数据"], WHITE),
            architecture_box(425, 810, 280, 145, "SQLite", ["会话 · 反馈 · 情绪", "配置 · 实时运营"], WHITE),
            architecture_box(745, 810, 280, 145, "模型与形象资源", ["CPU / RAM 待机", "空闲 GPU 动态选择"], WHITE),
            architecture_box(1065, 810, 280, 145, "历史数据集", ["140447 条游客记录", "152 个景点"], WHITE),
            rounded_box(420, 985, 610, 42, WHITE, ACCENT, 12),
            text_line(725, 1012, "GPU 生命周期：请求触发加载，连续请求复用，空闲 180 秒后释放", "small", "middle"),
        ]
    )
    return svg_document(width, height, "灵山小向导系统总体架构图", "\n".join(items))


def sequence_arrow(start_x: float, end_x: float, y: float, label: str, response: bool = False) -> str:
    dashed = ' stroke-dasharray="9 7"' if response else ""
    middle_x = (start_x + end_x) / 2
    label_y = y - 12
    return "".join(
        [
            f'<line x1="{start_x}" y1="{y}" x2="{end_x}" y2="{y}" stroke="{ACCENT if response else INK}" stroke-width="2.5"{dashed} marker-end="url(#{"arrow-accent" if response else "arrow"})"/>',
            text_line(middle_x, label_y, label, "small", "middle"),
        ]
    )


def build_sequence() -> str:
    width, height = 1510, 1210
    centers = [130, 380, 630, 880, 1130, 1380]
    names = ["游客端", "FastAPI 网关", "GLM-ASR", "RAG + FAISS", "GLM 模型服务", "LiveTalking"]
    items: list[str] = [
        text_line(65, 62, "语音问答与数字人播报时序图", "title"),
        text_line(65, 94, "从录音结束到 WebRTC 数字人开口的流式处理链路", "subtitle"),
    ]
    for center_x, name in zip(centers, names):
        items.append(rounded_box(center_x - 95, 125, 190, 62, WHITE, INK, 14, True))
        items.append(text_line(center_x, 164, name, "label", "middle"))
        items.append(f'<line x1="{center_x}" y1="187" x2="{center_x}" y2="1115" stroke="{GRID}" stroke-width="2" stroke-dasharray="8 8"/>')
    arrows = [
        (0, 1, 240, "1. HTTPS 上传 16 kHz WAV", False),
        (1, 2, 320, "2. 请求语音识别", False),
        (2, 1, 400, "3. transcript + emotion_event_id", True),
        (1, 3, 480, "4. chat_stream(message, session)", False),
        (3, 4, 650, "5. 检索上下文 + 会话历史", False),
        (4, 3, 730, "6. LLM token 流", True),
        (3, 1, 810, "7. SSE delta + citations", True),
        (1, 4, 890, "8. 按完整语义句请求 TTS", False),
        (4, 1, 970, "9. 流式 PCM", True),
        (1, 5, 1050, "10. 合并 WAV 并加入播报队列", False),
        (5, 0, 1130, "11. WebRTC 音视频 + 口型", True),
    ]
    for start, end, y, label, response in arrows:
        items.append(sequence_arrow(centers[start], centers[end], y, label, response))
    items.extend(
        [
            rounded_box(755, 515, 250, 105, PALE_GREEN, GRID, 14),
            multiline_text(880, 550, ["BGE-M3 / FAISS 检索", "按需 GPU；180 秒回收"], "small", "middle", 26),
            polyline([(880, 515), (880, 500)], arrow=False, dashed=True),
            rounded_box(240, 835, 280, 72, PALE_GOLD, GRID, 14),
            multiline_text(380, 866, ["SpeechSegmenter", "完整语义句边界"], "small", "middle", 24),
            rounded_box(385, 1162, 740, 34, PALE_RED, ACCENT, 10),
            text_line(755, 1185, "LLM 生成、TTS 合成与数字人推理流水并行，不等待全文完成", "small", "middle"),
        ]
    )
    return svg_document(width, height, "灵山小向导语音问答时序图", "\n".join(items))


def entity_box(x: float, y: float, width: float, title: str, rows: list[tuple[str, str]], fill: str = WHITE) -> tuple[str, float]:
    header_height = 48
    row_height = 30
    height = header_height + row_height * len(rows) + 12
    elements = [rounded_box(x, y, width, height, fill, INK, 12, True), f'<path d="M {x} {y + header_height} H {x + width}" stroke="{INK}" stroke-width="2"/>', text_line(x + 16, y + 32, title, "label")]
    for index, (key, field) in enumerate(rows):
        baseline = y + header_height + 23 + index * row_height
        if index:
            elements.append(f'<line x1="{x + 12}" y1="{baseline - 21}" x2="{x + width - 12}" y2="{baseline - 21}" stroke="#D8E0DC" stroke-width="1"/>')
        elements.append(text_line(x + 16, baseline, key, "tiny", fill=ACCENT if key else MUTED))
        elements.append(text_line(x + 76, baseline, field, "mono"))
    return "".join(elements), height


def relationship_label(x: float, y: float, value: str) -> str:
    return "".join([rounded_box(x - 34, y - 18, 68, 29, WHITE, GRID, 8), text_line(x, y + 3, value, "tiny", "middle")])


def build_er() -> str:
    width, height = 1510, 1520
    items: list[str] = [
        text_line(65, 62, "核心数据 ER 图", "title"),
        text_line(65, 94, "SQLite 实体、逻辑会话键与历史数据导入关系", "subtitle"),
        f'<rect x="50" y="120" width="1410" height="790" rx="24" fill="{PALE_GREEN}" fill-opacity="0.25" stroke="{GRID}" stroke-width="1.5"/>',
        text_line(78, 155, "实时交互与运营数据", "label"),
        f'<rect x="50" y="955" width="1410" height="515" rx="24" fill="#EDF1F3" fill-opacity="0.65" stroke="{GRID}" stroke-width="1.5"/>',
        text_line(78, 990, "赛题历史游客数据", "label"),
    ]
    items.extend(
        [
            polyline([(750, 245), (245, 245), (245, 300)], dashed=True, arrow=False),
            polyline([(750, 245), (750, 300)], dashed=True, arrow=False),
            polyline([(750, 245), (1250, 245), (1250, 300)], dashed=True, arrow=False),
            polyline([(1090, 520), (1020, 520), (1020, 620), (920, 620)], arrow=False),
            polyline([(1090, 600), (990, 600), (990, 760), (920, 760)], arrow=False),
            polyline([(410, 1155), (585, 1155)], arrow=False),
            polyline([(410, 1195), (500, 1195), (500, 1015), (1025, 1015), (1025, 1155), (1090, 1155)], arrow=False),
            relationship_label(245, 265, "0..N"),
            relationship_label(750, 265, "0..N"),
            relationship_label(1250, 265, "0..N"),
            relationship_label(1048, 520, "0..N"),
            relationship_label(990, 680, "1 : N"),
            relationship_label(500, 1155, "1 : N"),
            relationship_label(1025, 1195, "1 : N"),
        ]
    )
    logical_session, _ = entity_box(585, 175, 330, "session_id（逻辑会话键）", [("", "无独立会话表"), ("", "由应用层关联")], PALE_GOLD)
    chat_logs, _ = entity_box(80, 300, 330, "chat_logs", [("PK", "id TEXT"), ("AK*", "session_id TEXT"), ("", "role TEXT"), ("", "content TEXT"), ("", "meta JSON/TEXT"), ("", "created_at TEXT")])
    emotion_events, _ = entity_box(585, 300, 330, "emotion_events", [("PK", "id TEXT"), ("AK*", "session_id TEXT"), ("", "source / transcript"), ("", "emotion_label / scores"), ("", "sentiment / valence"), ("", "aspects JSON/TEXT"), ("", "status / model_name"), ("", "created_at / completed_at")])
    feedback, _ = entity_box(1090, 300, 330, "feedback", [("PK", "id TEXT"), ("AK*", "session_id TEXT"), ("FK*", "attraction_id TEXT"), ("FK*", "emotion_event_id TEXT"), ("", "rating INTEGER"), ("", "comment / sentiment"), ("", "created_at TEXT")])
    avatar, _ = entity_box(80, 650, 330, "avatar_settings", [("PK", "id = 1"), ("", "display_name TEXT"), ("", "avatar_id TEXT"), ("", "voice TEXT"), ("", "expression TEXT"), ("", "updated_at TEXT")], PALE_GOLD)
    attractions, _ = entity_box(585, 650, 335, "attractions", [("PK", "id TEXT"), ("", "scenic_area_id TEXT"), ("", "scenic_area TEXT"), ("", "attraction_name TEXT"), ("", "is_overall INTEGER"), ("", "source_document TEXT")], PALE_GOLD)
    imports, _ = entity_box(80, 1060, 330, "dataset_imports", [("PK", "source_file TEXT"), ("", "source_path TEXT"), ("", "source_signature TEXT"), ("", "row_count INTEGER"), ("", "imported_at TEXT")], PALE_GOLD)
    visits, _ = entity_box(585, 1030, 360, "tourism_visits", [("PK", "id INTEGER"), ("FK*", "source_file TEXT"), ("UK", "source_file + dataset_row"), ("", "tourist_id / nickname"), ("", "attraction_name / type"), ("", "visit_date / stay_duration"), ("", "各类消费 / group_size"), ("", "satisfaction INTEGER")])
    contents, _ = entity_box(1090, 1060, 330, "tourism_attraction_contents", [("PK", "source_file + content_key"), ("FK*", "source_file TEXT"), ("", "attraction_name TEXT"), ("", "attraction_type TEXT"), ("", "attraction_content TEXT")], PALE_GOLD)
    items.extend([logical_session, chat_logs, emotion_events, feedback, avatar, attractions, imports, visits, contents])
    items.append(rounded_box(440, 1468, 630, 34, WHITE, ACCENT, 10))
    items.append(text_line(755, 1491, "AK* / FK* 表示应用层关联；当前 SQLite 未声明 FOREIGN KEY 约束", "small", "middle"))
    return svg_document(width, height, "灵山小向导核心数据 ER 图", "\n".join(items))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    diagrams = {
        "01-use-case.svg": build_use_case(),
        "02-system-architecture.svg": build_architecture(),
        "03-voice-sequence.svg": build_sequence(),
        "04-data-er.svg": build_er(),
    }
    for filename, content in diagrams.items():
        path = OUTPUT_DIR / filename
        path.write_text(content, encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
