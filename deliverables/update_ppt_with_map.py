from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "A5-灵山小向导-产品方案介绍-final.pptx"
MAP_SLIDE = Path("/tmp/cup-map-feature-slide.pptx")
OUTPUT = ROOT / "A5-灵山小向导-产品方案介绍-地图功能更新版.pptx"

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
    "app": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}

for prefix in ("a", "p", "r", "cp", "dcterms", "vt"):
    ET.register_namespace(prefix, NS[prefix])
ET.register_namespace("", NS["pr"])


def xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def shape_by_id(root: ET.Element, shape_id: str) -> ET.Element:
    for shape in root.findall(".//p:sp", NS):
        props = shape.find("./p:nvSpPr/p:cNvPr", NS)
        if props is not None and props.get("id") == shape_id:
            return shape
    raise KeyError(f"shape {shape_id} not found")


def replace_shape_text(root: ET.Element, shape_id: str, lines: list[str] | str) -> None:
    if isinstance(lines, str):
        lines = [lines]
    shape = shape_by_id(root, shape_id)
    body = shape.find("./p:txBody", NS)
    if body is None:
        raise KeyError(f"shape {shape_id} has no text body")
    paragraphs = body.findall("./a:p", NS)
    template = paragraphs[0] if paragraphs else None
    p_pr = copy.deepcopy(template.find("./a:pPr", NS)) if template is not None else None
    run_pr = None
    end_pr = None
    if template is not None:
        run = template.find("./a:r", NS)
        if run is not None:
            run_pr = copy.deepcopy(run.find("./a:rPr", NS))
        end_pr = copy.deepcopy(template.find("./a:endParaRPr", NS))
    for paragraph in paragraphs:
        body.remove(paragraph)
    for value in lines:
        paragraph = ET.SubElement(body, f"{{{NS['a']}}}p")
        if p_pr is not None:
            paragraph.append(copy.deepcopy(p_pr))
        run = ET.SubElement(paragraph, f"{{{NS['a']}}}r")
        if run_pr is not None:
            run.append(copy.deepcopy(run_pr))
        node = ET.SubElement(run, f"{{{NS['a']}}}t")
        node.text = value
        if end_pr is not None:
            paragraph.append(copy.deepcopy(end_pr))


def patch_slide(data: bytes, replacements: dict[str, list[str] | str]) -> bytes:
    root = ET.fromstring(data)
    for shape_id, value in replacements.items():
        replace_shape_text(root, shape_id, value)
    return xml_bytes(root)


def numeric_footer_shape(root: ET.Element) -> str | None:
    for shape in root.findall(".//p:sp", NS):
        props = shape.find("./p:nvSpPr/p:cNvPr", NS)
        off = shape.find("./p:spPr/a:xfrm/a:off", NS)
        texts = shape.findall(".//a:t", NS)
        if props is None or off is None or not texts:
            continue
        x = int(off.get("x", "0")) / 914400
        y = int(off.get("y", "0")) / 914400
        value = "".join(text.text or "" for text in texts).strip()
        if x >= 11.5 and y >= 6.8 and re.fullmatch(r"\d{1,2}", value):
            return props.get("id")
    return None


def next_media_name(entries: dict[str, bytes], suffix: str) -> str:
    used = []
    pattern = re.compile(r"ppt/media/image(\d+)\.[^.]+$")
    for name in entries:
        match = pattern.fullmatch(name)
        if match:
            used.append(int(match.group(1)))
    return f"ppt/media/image{max(used, default=0) + 1}.{suffix}"


with ZipFile(BASE) as archive:
    entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}

with ZipFile(MAP_SLIDE) as archive:
    source_entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}

replacements = {
    1: {"14": "地图导览"},
    3: {
        "4": "游客每一次提问、路线、定位、识景和评价，都能成为下一轮服务优化的依据",
        "11": ["语音 / 文本", "兴趣 / 时间 / 同行", "当前位置"],
        "16": "规划讲解",
        "17": ["个性化地图路线", "RAG 引用", "景点知识"],
    },
    4: {
        "4": "问答、地图路线、识景、定位",
        "19": "路线偏好输入",
        "31": "地图路线",
    },
    5: {
        "4": "网关统一会话与权限；检索、生成、地图、视觉、语音、情感和数字人按能力解耦",
        "11": "问答生成",
        "24": ["BGE-M3 + FAISS", "SQLite + 地图点位", "140,447 条历史数据"],
    },
    8: {
        "4": "把低置信度当作产品状态；确认位置可作为地图起点，再开始有依据的讲解",
    },
    15: {
        "38": "拟真数字人失败回退 Live2D；地图底图失败仍保留站点顺序与导航入口。",
    },
    21: {
        "10": ["个性化讲解、地图路线、识景与定位", "情绪感知让交互更亲切"],
        "23": "补齐园内实测坐标、步道网络、BSSID / 蓝牙信标与授权图库",
    },
}

for slide_number, slide_replacements in replacements.items():
    name = f"ppt/slides/slide{slide_number}.xml"
    entries[name] = patch_slide(entries[name], slide_replacements)

# Renumber every existing numeric footer by physical slide order. The new map
# slide is inserted at position 5, so files slide5.xml and later shift by one.
for slide_number in range(2, 21):
    name = f"ppt/slides/slide{slide_number}.xml"
    root = ET.fromstring(entries[name])
    footer_id = numeric_footer_shape(root)
    if footer_id:
        physical_number = slide_number if slide_number < 5 else slide_number + 1
        replace_shape_text(root, footer_id, f"{physical_number:02d}")
        entries[name] = xml_bytes(root)

# Add the generated map slide as slide22.xml and remap its media relationships.
new_slide_number = 22
new_slide_name = f"ppt/slides/slide{new_slide_number}.xml"
new_rels_name = f"ppt/slides/_rels/slide{new_slide_number}.xml.rels"
entries[new_slide_name] = source_entries["ppt/slides/slide1.xml"]

source_rels = ET.fromstring(source_entries["ppt/slides/_rels/slide1.xml.rels"])
for relation in list(source_rels):
    target = relation.get("Target", "")
    if relation.get("Type", "").endswith("/notesSlide"):
        # The generated one-slide source contains a notes relationship even
        # without speaker notes. Reusing notesSlide1 would make two slides
        # claim the same notes part, so the inserted slide intentionally has
        # no notes relationship.
        source_rels.remove(relation)
        continue
    if target.startswith("../media/"):
        source_media = f"ppt/media/{Path(target).name}"
        suffix = Path(target).suffix.lstrip(".")
        destination = next_media_name(entries, suffix)
        entries[destination] = source_entries[source_media]
        relation.set("Target", f"../media/{Path(destination).name}")
entries[new_rels_name] = xml_bytes(source_rels)

# Insert the new slide relationship after the existing fourth slide.
presentation_rels = ET.fromstring(entries["ppt/_rels/presentation.xml.rels"])
relationship_ids = [int(item.get("Id", "rId0").removeprefix("rId")) for item in presentation_rels]
new_relationship_id = f"rId{max(relationship_ids) + 1}"
ET.SubElement(
    presentation_rels,
    f"{{{NS['pr']}}}Relationship",
    {
        "Id": new_relationship_id,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
        "Target": f"slides/slide{new_slide_number}.xml",
    },
)
entries["ppt/_rels/presentation.xml.rels"] = xml_bytes(presentation_rels)

presentation = ET.fromstring(entries["ppt/presentation.xml"])
slide_list = presentation.find("./p:sldIdLst", NS)
if slide_list is None:
    raise RuntimeError("presentation has no slide list")
slide_ids = [int(item.get("id", "0")) for item in slide_list]
new_slide_id = ET.Element(
    f"{{{NS['p']}}}sldId",
    {
        "id": str(max(slide_ids) + 1),
        f"{{{NS['r']}}}id": new_relationship_id,
    },
)
slide_list.insert(4, new_slide_id)
entries["ppt/presentation.xml"] = xml_bytes(presentation)

content_types = entries["[Content_Types].xml"]
content_type_override = (
    f'<Override PartName="/ppt/slides/slide{new_slide_number}.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
).encode("utf-8")
if content_type_override not in content_types:
    # Keep the original default namespace declaration verbatim. LibreOffice's
    # PPTX importer rejects a semantically equivalent ns0-prefixed Types root.
    content_types = content_types.replace(b"</Types>", content_type_override + b"</Types>")
entries["[Content_Types].xml"] = content_types

app_props = ET.fromstring(entries["docProps/app.xml"])
slides_node = app_props.find(f"{{{NS['app']}}}Slides")
if slides_node is not None:
    slides_node.text = "22"
for vector in app_props.findall(f".//{{{NS['vt']}}}vector"):
    values = list(vector)
    if any(item.tag == f"{{{NS['vt']}}}lpstr" and item.text == "PowerPoint 演示文稿" for item in values):
        ET.SubElement(vector, f"{{{NS['vt']}}}lpstr").text = "PowerPoint 演示文稿"
        vector.set("size", str(int(vector.get("size", "0")) + 1))
        break
for variant in app_props.findall(f".//{{{NS['vt']}}}variant"):
    label = variant.find(f"{{{NS['vt']}}}lpstr")
    if label is not None and label.text == "幻灯片标题":
        parent_vector = next((v for v in app_props.findall(f".//{{{NS['vt']}}}vector") if variant in list(v)), None)
        if parent_vector is not None:
            variants = list(parent_vector)
            index = variants.index(variant)
            if index + 1 < len(variants):
                count = variants[index + 1].find(f"{{{NS['vt']}}}i4")
                if count is not None:
                    count.text = "22"
        break
entries["docProps/app.xml"] = xml_bytes(app_props)

core_props = ET.fromstring(entries["docProps/core.xml"])
modified = core_props.find(f"{{{NS['dcterms']}}}modified")
if modified is not None:
    modified.text = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
entries["docProps/core.xml"] = xml_bytes(core_props)

with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
    for name, data in entries.items():
        archive.writestr(name, data)

print(f"Updated PPTX written: {OUTPUT}")
