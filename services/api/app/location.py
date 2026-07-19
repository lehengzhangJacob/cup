from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
import time
from typing import Any, Optional

from .attractions import attraction_catalog


# Demo anchors in WGS-84. Before production deployment these points should be
# replaced by coordinates surveyed and approved by the scenic-area operator.
SPOT_ANCHORS: dict[str, dict[str, Any]] = {
    "LS-001": {"name": "灵山大照壁", "lat": 31.4148, "lng": 120.9975},
    "LS-006": {"name": "九龙灌浴", "lat": 31.4172, "lng": 120.9984},
    "LS-FO": {"name": "灵山大佛", "lat": 31.4221, "lng": 120.9986},
    "LS-FG": {"name": "灵山梵宫", "lat": 31.4192, "lng": 121.0026},
    "LS-WY": {"name": "五印坛城", "lat": 31.4203, "lng": 121.0046},
}

WIFI_ANCHORS: dict[str, dict[str, str]] = {
    "LS-WIFI-SOUTH": {"spot_id": "LS-001", "name": "南门/入口区"},
    "LS-WIFI-NINE": {"spot_id": "LS-006", "name": "九龙灌浴区域"},
    "LS-WIFI-BUDDHA": {"spot_id": "LS-FO", "name": "灵山大佛区域"},
    "LS-WIFI-BRAHMA": {"spot_id": "LS-FG", "name": "灵山梵宫区域"},
}


def _qr_points() -> dict[str, dict[str, str]]:
    """All published scenic QR points, independent from GPS coverage.

    A QR code identifies the point where it is installed, so it remains useful
    in indoor/blocked-GPS areas even before that point has a surveyed GPS
    coordinate.  Only five GPS anchors are currently configured below.
    """
    points: dict[str, dict[str, str]] = {}
    for area in attraction_catalog():
        for item in area["children"]:
            if item["is_overall"]:
                continue
            points[str(item["id"])] = {
                "spot_id": str(item["id"]),
                "attraction_id": str(item["id"]),
                "spot_name": str(item["name"]),
                "scenic_area": str(area["name"]),
            }
    # Backward-compatible labels printed by an early demo QR set.
    points["LS-FO"] = {
        "spot_id": "LS-FO",
        "attraction_id": "LS-011",
        "spot_name": "灵山大佛",
        "scenic_area": "灵山胜境",
    }
    points["LS-FG"] = {
        "spot_id": "LS-FG",
        "attraction_id": "LS-013",
        "spot_name": "灵山梵宫",
        "scenic_area": "灵山胜境",
    }
    points["LS-WY"] = {
        "spot_id": "LS-WY",
        "attraction_id": "LS-014",
        "spot_name": "五印坛城",
        "scenic_area": "灵山胜境",
    }
    return points


def location_options() -> dict[str, Any]:
    points = _qr_points()
    published = [value for key, value in points.items() if key == value["attraction_id"]]
    return {
        "points": sorted(published, key=lambda item: item["spot_id"]),
        "wifi_nodes": [
            {"code": code, "name": node["name"], "spot_id": node["spot_id"]}
            for code, node in WIFI_ANCHORS.items()
        ],
        "gps_anchor_count": len(SPOT_ANCHORS),
        "gps_coverage_note": "GPS 仅对已标定锚点自动匹配；其他景点请使用景点二维码或手动确认。",
        "strategy": "GPS → 摄像头扫描景点二维码 → 景区 Wi-Fi 区域 → 手动选择",
    }

FALLBACKS = [
    {"mode": "qr", "label": "扫描景点二维码", "note": "室内和建筑遮挡区优先使用"},
    {"mode": "wifi", "label": "景区 Wi-Fi 点位", "note": "按接入点区域进行近似定位"},
    {"mode": "manual", "label": "手动选择景点", "note": "始终可用，不依赖定位权限"},
]

GPS_GOOD_ACCURACY_M = 40.0
GPS_USABLE_ACCURACY_M = 120.0
GPS_CANDIDATE_RADIUS_M = 600.0
GPS_MATCH_RADIUS_M = 320.0
GPS_MAX_AGE_SECONDS = 120.0


def _fallbacks() -> list[dict[str, str]]:
    return [dict(item) for item in FALLBACKS]


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance using a stable haversine implementation."""
    earth_radius_m = 6_371_000.0
    lat1r, lat2r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    value = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlng / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(value))


def _nearest_spot(lat: float, lng: float) -> tuple[str, dict[str, Any], float]:
    candidates = (
        (spot_id, spot, _distance_m(lat, lng, spot["lat"], spot["lng"]))
        for spot_id, spot in SPOT_ANCHORS.items()
    )
    return min(candidates, key=lambda item: item[2])


def _base(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "resolved": False,
        "confidence": "none",
        "strategy": "GPS → 摄像头扫描景点二维码 → 景区 Wi-Fi 区域 → 手动选择",
        "fallbacks": _fallbacks(),
    }


def resolve_location(
    mode: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    accuracy_m: Optional[float] = None,
    timestamp_ms: Optional[float] = None,
    code: Optional[str] = None,
    spot_name: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve a visitor position without pretending weak signals are precise."""
    normalized_mode = (mode or "").strip().lower()
    result = _base(normalized_mode)

    if normalized_mode == "gps":
        if lat is None or lng is None:
            return {
                **result,
                "reason": "missing_coordinates",
                "note": "没有收到 GPS 坐标，请使用二维码、景区 Wi-Fi 或手动选择。",
            }
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return {
                **result,
                "reason": "invalid_coordinates",
                "note": "GPS 坐标格式无效，已停止自动匹配。",
            }

        accuracy = float(accuracy_m) if accuracy_m is not None else None
        if accuracy is not None and accuracy <= 0:
            accuracy = None
        age_seconds = None
        if timestamp_ms is not None:
            age_seconds = max(0.0, time.time() - float(timestamp_ms) / 1000.0)

        spot_id, spot, distance_m = _nearest_spot(float(lat), float(lng))
        candidate = {
            "spot_id": spot_id,
            "attraction_id": _qr_points().get(spot_id, {}).get("attraction_id"),
            "spot_name": spot["name"],
            "distance_m": round(distance_m),
        }
        gps_meta = {
            "accuracy_m": round(accuracy) if accuracy is not None else None,
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            **candidate,
        }

        if age_seconds is not None and age_seconds > GPS_MAX_AGE_SECONDS:
            return {
                **result,
                **gps_meta,
                "reason": "stale_position",
                "requires_confirmation": True,
                "note": "GPS 位置已经过期，不能据此自动讲解，请重新定位或选择点位。",
            }
        if accuracy is None or accuracy > GPS_USABLE_ACCURACY_M:
            return {
                **result,
                **gps_meta,
                "reason": "weak_signal",
                "requires_confirmation": distance_m <= GPS_CANDIDATE_RADIUS_M,
                "note": "GPS 信号较弱，仅给出候选景点，不会自动认定游客位置。",
            }
        if distance_m > GPS_MATCH_RADIUS_M:
            return {
                **result,
                **gps_meta,
                "reason": "outside_coverage",
                "requires_confirmation": distance_m <= GPS_CANDIDATE_RADIUS_M,
                "note": "坐标未落入已标定景点范围，请扫描附近二维码或手动选择。",
            }

        confidence = "high" if accuracy <= GPS_GOOD_ACCURACY_M and distance_m <= 160 else "medium"
        return {
            **result,
            **gps_meta,
            "resolved": True,
            "confidence": confidence,
            "source_label": "GPS 高精度定位" if confidence == "high" else "GPS 辅助定位",
            "requires_confirmation": confidence != "high",
            "note": "已按 GPS 精度、位置时效和最近点位距离完成校验。",
        }

    if normalized_mode == "qr":
        normalized_code = (code or "").strip().upper()
        point = _qr_points().get(normalized_code)
        spot = SPOT_ANCHORS.get(normalized_code)
        if point:
            return {
                **result,
                "resolved": True,
                "confidence": "high",
                "source_label": "景点二维码",
                **point,
                "code": normalized_code,
                "note": "二维码绑定固定点位，适合 GPS 弱信号和室内区域。",
            }
        if not spot:
            return {
                **result,
                "code": normalized_code,
                "reason": "unknown_qr",
                "note": "未识别该景点码，请重新扫描或手动选择景点。",
            }
        return {
            **result,
            "resolved": True,
            "confidence": "high",
            "source_label": "景点二维码",
            "spot_id": normalized_code,
            "attraction_id": _qr_points().get(normalized_code, {}).get("attraction_id"),
            "spot_name": spot["name"],
            "code": normalized_code,
            "note": "二维码绑定固定点位，适合 GPS 弱信号和室内区域。",
        }

    if normalized_mode == "wifi":
        normalized_code = (code or "").strip().upper()
        node = WIFI_ANCHORS.get(normalized_code)
        if not node:
            return {
                **result,
                "code": normalized_code,
                "reason": "unknown_wifi_node",
                "note": "当前 Wi-Fi 节点尚未标定，请改用二维码或手动选择。",
            }
        return {
            **result,
            "resolved": True,
            "confidence": "medium",
            "source_label": "景区 Wi-Fi 区域定位",
            "spot_id": node["spot_id"],
            "attraction_id": _qr_points().get(node["spot_id"], {}).get("attraction_id"),
            "spot_name": node["name"],
            "code": normalized_code,
            "requires_confirmation": True,
            "note": "Wi-Fi 只能判断所在区域，导览前建议游客确认附近标志物。",
        }

    if normalized_mode == "manual":
        normalized_name = (spot_name or "").strip()
        if not normalized_name:
            return {
                **result,
                "reason": "missing_spot",
                "note": "请选择当前所在景点。",
            }
        known_point = next(
            (point for point in _qr_points().values() if point["spot_name"] == normalized_name),
            None,
        )
        known_spot = next(
            ((spot_id, spot) for spot_id, spot in SPOT_ANCHORS.items() if spot["name"] == normalized_name),
            None,
        )
        return {
            **result,
            "resolved": True,
            "confidence": "user_confirmed",
            "source_label": "游客手动确认",
            "spot_id": (known_point or {}).get("spot_id") or (known_spot[0] if known_spot else None),
            "attraction_id": (known_point or {}).get("attraction_id"),
            "spot_name": normalized_name,
            "requires_confirmation": False,
            "note": "位置由游客确认，不依赖 GPS 信号。",
        }

    return {
        **result,
        "reason": "unsupported_mode",
        "note": "不支持的定位方式，请使用 GPS、二维码、景区 Wi-Fi 或手动选择。",
    }
