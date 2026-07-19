from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from xml.etree import ElementTree as ET

from .config import DATA_DIR, LOG_DB, TOURISM_DATASET_PATH


_XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CELL_RE = re.compile(r"([A-Z]+)")
_CACHE_VERSION = 2
TOURISM_COLUMNS = (
    "tourist_id",
    "user_nickname",
    "age",
    "gender",
    "attraction_name",
    "attraction_content",
    "attraction_type",
    "visit_date",
    "stay_duration",
    "ticket_cost",
    "food_cost",
    "shopping_cost",
    "transport_cost",
    "entertainment_cost",
    "total_cost",
    "group_size",
    "satisfaction",
)


def ensure_tourism_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tourism_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            dataset_row INTEGER NOT NULL,
            tourist_id TEXT,
            user_nickname TEXT,
            age INTEGER,
            gender TEXT,
            attraction_name TEXT,
            attraction_content TEXT,
            attraction_type TEXT,
            visit_date TEXT,
            stay_duration REAL,
            ticket_cost REAL,
            food_cost REAL,
            shopping_cost REAL,
            transport_cost REAL,
            entertainment_cost REAL,
            total_cost REAL,
            group_size INTEGER,
            satisfaction INTEGER,
            imported_at TEXT NOT NULL,
            UNIQUE(source_file, dataset_row)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_imports (
            source_file TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_signature TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tourism_visits_attraction "
        "ON tourism_visits(attraction_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tourism_visits_date "
        "ON tourism_visits(visit_date)"
    )


def _database_signature(source: Path) -> str:
    stat = source.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def import_tourism_dataset(
    db_path: Path = LOG_DB,
    source: Path = TOURISM_DATASET_PATH,
    force: bool = False,
) -> dict[str, Any]:
    if not source.exists():
        return {"available": False, "source": str(source), "detail": "XLSX 数据文件不存在"}
    signature = _database_signature(source)
    source_file = source.name
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_tourism_schema(conn)
        previous = conn.execute(
            "SELECT source_signature, row_count, imported_at FROM dataset_imports WHERE source_file=?",
            (source_file,),
        ).fetchone()
        if previous and previous[0] == signature and not force:
            conn.commit()
            return {
                "available": True,
                "changed": False,
                "source": source_file,
                "rows": int(previous[1]),
                "imported_at": previous[2],
            }

        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in range(len(TOURISM_COLUMNS) + 3))
        insert_sql = (
            "INSERT INTO tourism_visits "
            "(source_file,dataset_row," + ",".join(TOURISM_COLUMNS) + ",imported_at) "
            f"VALUES ({placeholders})"
        )
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tourism_visits WHERE source_file=?", (source_file,))
        batch: list[tuple[Any, ...]] = []
        count = 0
        for count, row in enumerate(iter_xlsx_rows(source), start=1):
            values: list[Any] = []
            for column in TOURISM_COLUMNS:
                value = row.get(column)
                if column == "visit_date":
                    value = _excel_date(value)
                if value == "":
                    value = None
                values.append(value)
            batch.append((source_file, count, *values, now))
            if len(batch) >= 1000:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
        conn.execute(
            """
            INSERT INTO dataset_imports
                (source_file, source_path, source_signature, row_count, imported_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(source_file) DO UPDATE SET
                source_path=excluded.source_path,
                source_signature=excluded.source_signature,
                row_count=excluded.row_count,
                imported_at=excluded.imported_at
            """,
            (source_file, str(source), signature, count, now),
        )
        conn.commit()
        return {
            "available": True,
            "changed": True,
            "source": source_file,
            "rows": count,
            "imported_at": now,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def tourism_import_status(
    db_path: Path = LOG_DB,
    source: Path = TOURISM_DATASET_PATH,
) -> dict[str, Any]:
    if not db_path.exists():
        return {"imported": False, "rows": 0}
    conn = sqlite3.connect(db_path)
    try:
        ensure_tourism_schema(conn)
        row = conn.execute(
            "SELECT row_count, imported_at, source_path FROM dataset_imports WHERE source_file=?",
            (source.name,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        return {"imported": False, "rows": 0}
    return {
        "imported": True,
        "rows": int(row[0]),
        "imported_at": row[1],
        "source_path": row[2],
    }


def _column_index(reference: str) -> int:
    match = _CELL_RE.match(reference or "")
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _numeric(value: str) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open(path) as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag == f"{{{_XML_NS}}}si":
                strings.append(
                    "".join(
                        node.text or ""
                        for node in element.iter(f"{{{_XML_NS}}}t")
                    )
                )
                element.clear()
    return strings


def iter_xlsx_rows(path: Path) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        headers: list[str] = []
        with archive.open("xl/worksheets/sheet1.xml") as source:
            for _, element in ET.iterparse(source, events=("end",)):
                if element.tag != f"{{{_XML_NS}}}row":
                    continue
                values: dict[int, Any] = {}
                for cell in element.findall(f"{{{_XML_NS}}}c"):
                    index = _column_index(cell.get("r", ""))
                    kind = cell.get("t")
                    value_node = cell.find(f"{{{_XML_NS}}}v")
                    raw = value_node.text if value_node is not None else ""
                    if kind == "s" and raw:
                        value: Any = shared[int(raw)]
                    elif kind == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter(f"{{{_XML_NS}}}t")
                        )
                    else:
                        value = _numeric(raw)
                    values[index] = value

                width = max(values.keys(), default=-1) + 1
                row = [values.get(index, "") for index in range(width)]
                if not headers:
                    headers = [str(value) for value in row]
                else:
                    yield {
                        header: row[index] if index < len(row) else ""
                        for index, header in enumerate(headers)
                    }
                element.clear()


def _excel_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    text = str(value or "").strip()
    return text[:10]


def _age_bucket(age: float) -> str:
    if age < 25:
        return "24岁及以下"
    if age < 35:
        return "25–34岁"
    if age < 45:
        return "35–44岁"
    if age < 55:
        return "45–54岁"
    return "55岁以上"


def _spend_bucket(cost: float) -> str:
    if cost < 300:
        return "300元以下"
    if cost < 800:
        return "300–799元"
    if cost < 1500:
        return "800–1499元"
    return "1500元以上"


class _Correlation:
    def __init__(self) -> None:
        self.n = 0
        self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0

    def add(self, x: float, y: float) -> None:
        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x * x
        self.syy += y * y
        self.sxy += x * y

    def value(self) -> float | None:
        if self.n < 2:
            return None
        numerator = self.n * self.sxy - self.sx * self.sy
        denominator = math.sqrt(
            max(0.0, self.n * self.sxx - self.sx * self.sx)
            * max(0.0, self.n * self.syy - self.sy * self.sy)
        )
        return round(numerator / denominator, 4) if denominator else None


def summarize_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    count = 0
    satisfaction = Counter()
    satisfaction_sum = 0.0
    tourists: set[str] = set()
    attractions: set[str] = set()
    dates: list[str] = []
    type_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    month_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    age_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    spend_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    attraction_stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    scenic_samples: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    correlations = {
        "总消费": _Correlation(),
        "停留时长": _Correlation(),
        "门票消费": _Correlation(),
        "餐饮消费": _Correlation(),
    }

    for row in rows:
        try:
            score = int(float(row.get("satisfaction", 0)))
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 5:
            continue
        count += 1
        satisfaction[score] += 1
        satisfaction_sum += score
        tourist = str(row.get("tourist_id") or "")
        attraction = str(row.get("attraction_name") or "未知景点")
        attraction_type = str(row.get("attraction_type") or "其他")
        if tourist:
            tourists.add(tourist)
        attractions.add(attraction)
        date = _excel_date(row.get("visit_date"))
        if date:
            dates.append(date)
            month = date[:7]
            month_stats[month][0] += 1
            month_stats[month][1] += score

        age = float(row.get("age") or 0)
        age_stats[_age_bucket(age)][0] += 1
        age_stats[_age_bucket(age)][1] += score
        total_cost = float(row.get("total_cost") or 0)
        spend_stats[_spend_bucket(total_cost)][0] += 1
        spend_stats[_spend_bucket(total_cost)][1] += score
        type_stats[attraction_type][0] += 1
        type_stats[attraction_type][1] += score
        attraction_stats[attraction][0] += 1
        attraction_stats[attraction][1] += score
        # The public dataset includes records for both competition destinations.
        # Keep this scoped card separate from the overall 100+ scenic attractions.
        if any(keyword in attraction for keyword in ("灵山", "拈花湾")):
            scenic_samples[attraction][0] += 1
            scenic_samples[attraction][1] += score

        correlations["总消费"].add(total_cost, score)
        correlations["停留时长"].add(float(row.get("stay_duration") or 0), score)
        correlations["门票消费"].add(float(row.get("ticket_cost") or 0), score)
        correlations["餐饮消费"].add(float(row.get("food_cost") or 0), score)

    def series(stats: dict[str, list[float]], order: list[str] | None = None):
        keys = order or sorted(stats)
        return [
            {
                "name": key,
                "count": int(stats[key][0]),
                "avg_satisfaction": round(stats[key][1] / stats[key][0], 3),
            }
            for key in keys
            if stats[key][0]
        ]

    satisfaction_rows = [
        {
            "score": score,
            "count": satisfaction.get(score, 0),
            "percentage": round(satisfaction.get(score, 0) / count * 100, 2)
            if count
            else 0,
        }
        for score in range(1, 6)
    ]
    top_attractions = sorted(
        series(attraction_stats),
        key=lambda item: item["count"],
        reverse=True,
    )[:12]
    return {
        "available": bool(count),
        "source": TOURISM_DATASET_PATH.name,
        "scope_note": "2025 年公开样例历史数据，与实时游客交互数据分开展示",
        "rows": count,
        "tourists": len(tourists),
        "attractions": len(attractions),
        "date_range": [min(dates), max(dates)] if dates else [],
        "avg_satisfaction": round(satisfaction_sum / count, 3) if count else None,
        "satisfaction_distribution": satisfaction_rows,
        "monthly_trend": [
            {
                "month": item["name"],
                "visits": item["count"],
                "avg_satisfaction": item["avg_satisfaction"],
            }
            for item in series(month_stats)
        ],
        "attraction_types": sorted(
            series(type_stats),
            key=lambda item: item["avg_satisfaction"],
            reverse=True,
        ),
        "age_groups": series(
            age_stats,
            ["24岁及以下", "25–34岁", "35–44岁", "45–54岁", "55岁以上"],
        ),
        "spend_groups": series(
            spend_stats,
            ["300元以下", "300–799元", "800–1499元", "1500元以上"],
        ),
        "scenic_samples": series(scenic_samples),
        "top_attractions": top_attractions,
        "correlations": [
            {"name": name, "value": tracker.value()}
            for name, tracker in correlations.items()
        ],
    }


class TourismAnalytics:
    def __init__(self, source: Path = TOURISM_DATASET_PATH) -> None:
        self.source = source
        self.cache_path = DATA_DIR / "tourism_analytics_cache.json"
        self._lock = threading.Lock()
        self._memory: dict[str, Any] | None = None
        self._signature: tuple[int, int] | None = None

    def _source_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.source.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _read_disk_cache(self, signature: tuple[int, int]) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if payload.get("_cache_version") != _CACHE_VERSION:
            return None
        if payload.get("_source_signature") != list(signature):
            return None
        payload.pop("_source_signature", None)
        payload.pop("_cache_version", None)
        return payload

    def load(self, force: bool = False) -> dict[str, Any]:
        signature = self._source_signature()
        if signature is None:
            return {
                "available": False,
                "source": str(self.source),
                "detail": "公开旅游行为数据文件不存在",
            }
        with self._lock:
            if not force and self._memory is not None and self._signature == signature:
                return {
                    **self._memory,
                    "database": tourism_import_status(source=self.source),
                }
            if not force:
                cached = self._read_disk_cache(signature)
                if cached is not None:
                    self._memory = cached
                    self._signature = signature
                    return {
                        **cached,
                        "database": tourism_import_status(source=self.source),
                    }

            result = summarize_rows(iter_xlsx_rows(self.source))
            result["source"] = self.source.name
            result["generated_at"] = datetime.now(timezone.utc).isoformat()
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "_cache_version": _CACHE_VERSION,
                "_source_signature": list(signature),
                **result,
            }
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(self.cache_path)
            self._memory = result
            self._signature = signature
            result["database"] = tourism_import_status(source=self.source)
            return result


tourism_analytics = TourismAnalytics()
