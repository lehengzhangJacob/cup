from __future__ import annotations

import sqlite3
from typing import Any


# The stable IDs and names below are transcribed from the two attraction tables
# in the competition's dataset.docx. Overall choices let visitors rate a scenic
# area even when they did not stop at one specific child attraction.
ATTRACTION_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "LS",
        "name": "灵山胜境",
        "children": (
            ("LS-ALL", "灵山胜境整体体验"),
            ("LS-001", "灵山大照壁"),
            ("LS-002", "五明桥"),
            ("LS-003", "佛足坛"),
            ("LS-004", "五智门"),
            ("LS-005", "菩提大道"),
            ("LS-006", "九龙灌浴"),
            ("LS-007", "降魔浮雕"),
            ("LS-008", "阿育王柱"),
            ("LS-009", "百子戏弥勒"),
            ("LS-010", "祥符禅寺"),
            ("LS-011", "灵山大佛"),
            ("LS-012", "佛教文化博览馆"),
            ("LS-013", "灵山梵宫"),
            ("LS-014", "五印坛城"),
            ("LS-015", "曼飞龙塔"),
            ("LS-016", "无尽意斋"),
        ),
    },
    {
        "id": "NH",
        "name": "拈花湾禅意小镇",
        "children": (
            ("NH-ALL", "拈花湾禅意小镇整体体验"),
            ("NH-001", "拈花广场"),
            ("NH-002", "梵天花海"),
            ("NH-003", "香月花街"),
            ("NH-004", "拈花堂"),
            ("NH-005", "五灯湖"),
            ("NH-006", "鹿鸣谷"),
        ),
    },
)


def attraction_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": group["id"],
            "name": group["name"],
            "children": [
                {"id": attraction_id, "name": name, "is_overall": attraction_id.endswith("-ALL")}
                for attraction_id, name in group["children"]
            ],
        }
        for group in ATTRACTION_GROUPS
    ]


def attraction_by_id(attraction_id: str) -> dict[str, str] | None:
    for group in ATTRACTION_GROUPS:
        for candidate, name in group["children"]:
            if candidate == attraction_id:
                return {
                    "id": candidate,
                    "scenic_area_id": str(group["id"]),
                    "scenic_area": str(group["name"]),
                    "name": name,
                }
    return None


def ensure_attraction_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attractions (
            id TEXT PRIMARY KEY,
            scenic_area_id TEXT NOT NULL,
            scenic_area TEXT NOT NULL,
            attraction_name TEXT NOT NULL,
            is_overall INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL,
            source_document TEXT NOT NULL
        )
        """
    )
    expected_count = sum(len(group["children"]) for group in ATTRACTION_GROUPS)
    current_count = conn.execute(
        "SELECT COUNT(*) FROM attractions WHERE source_document='dataset.docx'"
    ).fetchone()[0]
    if int(current_count) == expected_count:
        return
    rows = []
    order = 0
    for group in ATTRACTION_GROUPS:
        for attraction_id, name in group["children"]:
            rows.append(
                (
                    attraction_id,
                    group["id"],
                    group["name"],
                    name,
                    int(attraction_id.endswith("-ALL")),
                    order,
                    "dataset.docx",
                )
            )
            order += 1
    conn.executemany(
        """
        INSERT INTO attractions
            (id, scenic_area_id, scenic_area, attraction_name, is_overall,
             sort_order, source_document)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            scenic_area_id=excluded.scenic_area_id,
            scenic_area=excluded.scenic_area,
            attraction_name=excluded.attraction_name,
            is_overall=excluded.is_overall,
            sort_order=excluded.sort_order,
            source_document=excluded.source_document
        """,
        rows,
    )
