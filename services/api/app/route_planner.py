from __future__ import annotations

from math import asin, ceil, cos, radians, sin, sqrt
from typing import Any, Iterable
from urllib.parse import urlencode

from . import location
from .attractions import attraction_by_id, attraction_catalog


INTEREST_LABELS = {
    "history": "历史文化",
    "nature": "自然风光",
    "family": "亲子体验",
    "photo": "拍照打卡",
}
INTEREST_ALIASES = {
    "历史": "history",
    "历史文化": "history",
    "history": "history",
    "自然": "nature",
    "自然风光": "nature",
    "nature": "nature",
    "亲子": "family",
    "家庭": "family",
    "family": "family",
    "拍照": "photo",
    "摄影": "photo",
    "打卡": "photo",
    "photo": "photo",
}

# These profiles describe visit suitability, not coordinates. Coordinates are
# accepted only from location.py's source-backed or operator-configured anchors.
SPOT_PROFILES: dict[str, dict[str, Any]] = {
    "LS-001": {"minutes": 15, "interests": {"history": .7, "photo": .8}, "family": .8, "access": 1.0, "priority": .5},
    "LS-002": {"minutes": 15, "interests": {"history": .7, "photo": .6}, "family": .7, "access": .9, "priority": .35},
    "LS-003": {"minutes": 20, "interests": {"history": .9, "photo": .5}, "family": .6, "access": .8, "priority": .5},
    "LS-004": {"minutes": 15, "interests": {"history": .9, "photo": .6}, "family": .7, "access": .9, "priority": .45},
    "LS-005": {"minutes": 20, "interests": {"history": .7, "nature": .8, "photo": .7}, "family": .8, "access": 1.0, "priority": .55},
    "LS-006": {"minutes": 35, "interests": {"history": .8, "nature": .6, "family": 1.0, "photo": .9}, "family": 1.0, "access": .9, "priority": .95},
    "LS-007": {"minutes": 20, "interests": {"history": 1.0, "photo": .6}, "family": .6, "access": .8, "priority": .55},
    "LS-008": {"minutes": 20, "interests": {"history": 1.0, "photo": .7}, "family": .65, "access": .9, "priority": .6},
    "LS-009": {"minutes": 25, "interests": {"history": .7, "family": 1.0, "photo": .8}, "family": 1.0, "access": .9, "priority": .75},
    "LS-010": {"minutes": 30, "interests": {"history": 1.0, "nature": .5, "photo": .7}, "family": .55, "access": .75, "priority": .8},
    "LS-011": {"minutes": 55, "interests": {"history": 1.0, "nature": .7, "photo": 1.0}, "family": .65, "access": .45, "priority": 1.0, "note": "登台区域台阶较多，可在佛前广场完成轻量参观。"},
    "LS-012": {"minutes": 35, "interests": {"history": 1.0, "family": .65}, "family": .65, "access": .9, "priority": .6, "indoor": True},
    "LS-013": {"minutes": 50, "interests": {"history": 1.0, "photo": 1.0, "family": .65}, "family": .7, "access": .95, "priority": 1.0, "indoor": True},
    "LS-014": {"minutes": 35, "interests": {"history": 1.0, "photo": 1.0}, "family": .65, "access": .85, "priority": .85},
    "LS-015": {"minutes": 20, "interests": {"history": .85, "photo": .9}, "family": .65, "access": .75, "priority": .55},
    "LS-016": {"minutes": 45, "interests": {"history": .5, "family": .7}, "family": .8, "access": 1.0, "priority": .55, "indoor": True},
    "NH-001": {"minutes": 25, "interests": {"history": .6, "family": .8, "photo": .9}, "family": .9, "access": 1.0, "priority": .65},
    "NH-002": {"minutes": 45, "interests": {"nature": 1.0, "family": .9, "photo": 1.0}, "family": .9, "access": .9, "priority": .85},
    "NH-003": {"minutes": 55, "interests": {"history": .6, "nature": .7, "family": .9, "photo": 1.0}, "family": .9, "access": 1.0, "priority": 1.0},
    "NH-004": {"minutes": 30, "interests": {"history": 1.0, "photo": .8}, "family": .65, "access": .9, "priority": .75, "indoor": True},
    "NH-005": {"minutes": 45, "interests": {"nature": 1.0, "family": .8, "photo": 1.0}, "family": .85, "access": 1.0, "priority": .95},
    "NH-006": {"minutes": 50, "interests": {"nature": 1.0, "family": 1.0, "photo": .75}, "family": 1.0, "access": .6, "priority": .8, "note": "谷地游线距离较长，行动不便时建议缩短游览范围。"},
}

AREA_ENTRY = {"LS": "LS-006", "NH": "NH-002"}
PARTY_LABELS = {"adults": "成人同行", "family": "亲子家庭", "seniors": "长者同行"}
MOBILITY_LABELS = {"normal": "正常步行", "relaxed": "少走路", "accessible": "无障碍优先"}
WALKING_SPEED_M_PER_MINUTE = {"normal": 72.0, "relaxed": 55.0, "accessible": 48.0}
PATH_DISTANCE_FACTOR = 1.22

# The source anchors remain WGS-84 for provenance and GPS/location APIs.  The
# domestic map tiles and URI navigation entry point used by the visitor UI
# expect GCJ-02, so route rendering/navigation carries a converted coordinate
# alongside the original value.
AMAP_NAVIGATION_URL = "https://uri.amap.com/navigation"
AMAP_TILE_URL = "https://webrd0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}"


def _out_of_china(lat: float, lng: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    value = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * sqrt(abs(x))
    )
    value += (20.0 * sin(6.0 * x * 3.141592653589793) + 20.0 * sin(2.0 * x * 3.141592653589793)) * 2.0 / 3.0
    value += (20.0 * sin(y * 3.141592653589793) + 40.0 * sin(y / 3.0 * 3.141592653589793)) * 2.0 / 3.0
    value += (160.0 * sin(y / 12.0 * 3.141592653589793) + 320 * sin(y * 3.141592653589793 / 30.0)) * 2.0 / 3.0
    return value


def _transform_lng(x: float, y: float) -> float:
    value = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * sqrt(abs(x))
    )
    value += (20.0 * sin(6.0 * x * 3.141592653589793) + 20.0 * sin(2.0 * x * 3.141592653589793)) * 2.0 / 3.0
    value += (20.0 * sin(x * 3.141592653589793) + 40.0 * sin(x / 3.0 * 3.141592653589793)) * 2.0 / 3.0
    value += (150.0 * sin(x / 12.0 * 3.141592653589793) + 300.0 * sin(x / 30.0 * 3.141592653589793)) * 2.0 / 3.0
    return value


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """Convert WGS-84 latitude/longitude to mainland China's GCJ-02."""
    lat = float(lat)
    lng = float(lng)
    if _out_of_china(lat, lng):
        return lat, lng
    earth_axis = 6378245.0
    eccentricity = 0.00669342162296594323
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = radians(lat)
    magic = 1 - eccentricity * sin(rad_lat) ** 2
    sqrt_magic = sqrt(magic)
    d_lat = (d_lat * 180.0) / ((earth_axis * (1 - eccentricity)) / (magic * sqrt_magic) * 3.141592653589793)
    d_lng = (d_lng * 180.0) / (earth_axis / sqrt_magic * cos(rad_lat) * 3.141592653589793)
    return lat + d_lat, lng + d_lng


def _distance_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1, lng1 = radians(float(a["lat"])), radians(float(a["lng"]))
    lat2, lng2 = radians(float(b["lat"])), radians(float(b["lng"]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6_371_000.0 * asin(sqrt(value)) * PATH_DISTANCE_FACTOR


def _normalize_interests(interests: Iterable[str], legacy_interest: str) -> list[str]:
    normalized: list[str] = []
    for raw in [*interests, legacy_interest]:
        key = INTEREST_ALIASES.get(str(raw or "").strip().lower())
        if key and key not in normalized:
            normalized.append(key)
    return normalized[:4] or ["history"]


def _profile(spot_id: str) -> dict[str, Any]:
    return {
        "minutes": 30,
        "interests": {"history": .5, "nature": .5, "family": .5, "photo": .5},
        "family": .7,
        "access": .8,
        "priority": .5,
        **SPOT_PROFILES.get(spot_id, {}),
    }


def _visit_minutes(profile: dict[str, Any], party: str, mobility: str) -> int:
    minutes = int(profile["minutes"])
    if party in {"family", "seniors"}:
        minutes += 5
    if mobility in {"relaxed", "accessible"}:
        minutes += 5
    return minutes


def _score(
    point: dict[str, Any],
    *,
    interests: list[str],
    party: str,
    mobility: str,
    distance_m: float,
) -> float:
    profile = _profile(point["spot_id"])
    interest_score = max(float(profile["interests"].get(key, .2)) for key in interests)
    party_score = float(profile["family"]) if party == "family" else .75
    if party == "seniors":
        party_score = float(profile["access"])
    mobility_score = float(profile["access"]) if mobility != "normal" else .75
    return (
        interest_score * 4.0
        + float(profile["priority"]) * 2.0
        + party_score
        + mobility_score
        - (distance_m / 1000.0) * (1.5 if mobility != "normal" else .8)
    )


def _reason_labels(profile: dict[str, Any], interests: list[str], party: str, mobility: str) -> list[str]:
    matched = [
        INTEREST_LABELS[key]
        for key in interests
        if float(profile["interests"].get(key, 0)) >= .75
    ]
    if party == "family" and float(profile["family"]) >= .8:
        matched.append("亲子友好")
    if mobility != "normal" and float(profile["access"]) >= .85:
        matched.append("步行负担较低")
    return matched[:3] or ["顺路衔接"]


def _navigation_url(start: dict[str, Any], end: dict[str, Any]) -> str:
    start_lat, start_lng = wgs84_to_gcj02(start["lat"], start["lng"])
    end_lat, end_lng = wgs84_to_gcj02(end["lat"], end["lng"])

    def amap_point(point: dict[str, Any], lat: float, lng: float) -> str:
        # AMap URI navigation expects longitude,latitude[,name] in GCJ-02.
        name = str(point.get("spot_name") or point.get("name") or "").strip()
        return f"{lng:.6f},{lat:.6f},{name}" if name else f"{lng:.6f},{lat:.6f}"

    query = urlencode(
        {
            "from": amap_point(start, start_lat, start_lng),
            "to": amap_point(end, end_lat, end_lng),
            "mode": "walk",
            "policy": 1,
            "coordinate": "gaode",
            "callnative": 0,
        }
    )
    return f"{AMAP_NAVIGATION_URL}?{query}"


def _area_attraction_count(area_id: str) -> int:
    for area in attraction_catalog():
        if area["id"] == area_id:
            return sum(not item["is_overall"] for item in area["children"])
    return 0


def plan_personalized_route(
    *,
    scenic_area: str = "LS",
    duration_hours: float = 4.0,
    interests: Iterable[str] = (),
    legacy_interest: str = "历史",
    party: str = "adults",
    mobility: str = "normal",
    start_spot_id: str | None = None,
) -> dict[str, Any]:
    area_id = str(scenic_area or "LS").strip().upper()
    if area_id not in {"LS", "NH"}:
        area_id = "LS"
    party = party if party in PARTY_LABELS else "adults"
    mobility = mobility if mobility in MOBILITY_LABELS else "normal"
    selected_interests = _normalize_interests(interests, legacy_interest)
    budget_minutes = max(90, min(480, round(float(duration_hours) * 60)))
    speed = WALKING_SPEED_M_PER_MINUTE[mobility]

    points = [
        point
        for point in location.routable_map_points()
        if str(point["spot_id"]).startswith(f"{area_id}-")
    ]
    if not points:
        raise ValueError("当前景区尚未配置可用于地图规划的 WGS-84 点位")
    by_id = {point["spot_id"]: point for point in points}

    warnings: list[str] = []
    current = by_id.get(str(start_spot_id or "").upper())
    if start_spot_id and current is None:
        warnings.append("所选起点暂无可核验坐标，已从景区默认入口点开始规划。")
    current = current or by_id.get(AREA_ENTRY.get(area_id, ""))
    if current is None:
        current = max(
            points,
            key=lambda point: _score(
                point,
                interests=selected_interests,
                party=party,
                mobility=mobility,
                distance_m=0,
            ),
        )

    ordered: list[dict[str, Any]] = []
    remaining = {point["spot_id"]: point for point in points}
    planned_minutes = 0
    total_distance_m = 0.0
    previous: dict[str, Any] | None = None

    while current and len(ordered) < 8:
        profile = _profile(current["spot_id"])
        visit_minutes = _visit_minutes(profile, party, mobility)
        distance_m = _distance_m(previous, current) if previous else 0.0
        walk_minutes = ceil(distance_m / speed) if previous else 0
        added_minutes = visit_minutes + walk_minutes
        if ordered and planned_minutes + added_minutes > budget_minutes:
            break

        attraction = attraction_by_id(current["spot_id"]) or {}
        map_lat, map_lng = wgs84_to_gcj02(current["lat"], current["lng"])
        ordered.append(
            {
                **current,
                "map_lat": round(map_lat, 7),
                "map_lng": round(map_lng, 7),
                "scenic_area": attraction.get("scenic_area", current.get("scenic_area")),
                "visit_minutes": visit_minutes,
                "walk_minutes": walk_minutes,
                "distance_from_previous_m": round(distance_m),
                "reasons": _reason_labels(profile, selected_interests, party, mobility),
                "note": profile.get("note"),
                "navigation_url": _navigation_url(previous, current) if previous else None,
            }
        )
        planned_minutes += added_minutes
        total_distance_m += distance_m
        remaining.pop(current["spot_id"], None)
        previous = current

        candidates = []
        for point in remaining.values():
            candidate_profile = _profile(point["spot_id"])
            if mobility == "accessible" and float(candidate_profile["access"]) < .75:
                continue
            distance = _distance_m(current, point)
            visit = _visit_minutes(candidate_profile, party, mobility)
            walk = ceil(distance / speed)
            if planned_minutes + visit + walk > budget_minutes:
                continue
            candidates.append(
                (
                    _score(
                        point,
                        interests=selected_interests,
                        party=party,
                        mobility=mobility,
                        distance_m=distance,
                    ),
                    point,
                )
            )
        current = max(candidates, key=lambda item: item[0])[1] if candidates else None

    mapped_statuses = {str(stop.get("survey_status") or "") for stop in ordered}
    if mapped_statuses - {"field-verified", "operator-configured"}:
        warnings.append("地图点位含公开资料近似坐标，只用于游览顺序展示，抵达前请结合园内导览牌确认。")
    warnings.append("当前未接入景区实时开放时间与客流，出发前请以当日公告为准。")

    interest_text = "、".join(INTEREST_LABELS[item] for item in selected_interests[:2])
    area_name = "灵山胜境" if area_id == "LS" else "拈花湾禅意小镇"
    route_name = f"{area_name} {interest_text}路线"
    stop_names = "、".join(stop["spot_name"] for stop in ordered)
    summary = (
        f"从{ordered[0]['spot_name']}出发，按{MOBILITY_LABELS[mobility]}节奏安排"
        f"{len(ordered)}站：{stop_names}。"
    )
    total_spots = _area_attraction_count(area_id)
    mapped_count = len(points)
    return {
        "id": f"personalized-{area_id.lower()}",
        "name": route_name,
        "summary": summary,
        "scenic_area_id": area_id,
        "scenic_area": area_name,
        "duration_hours": round(budget_minutes / 60, 1),
        "planned_minutes": planned_minutes,
        "visit_minutes": sum(stop["visit_minutes"] for stop in ordered),
        "walk_minutes": sum(stop["walk_minutes"] for stop in ordered),
        "walking_distance_m": round(total_distance_m),
        "interests": selected_interests,
        "interest_labels": [INTEREST_LABELS[item] for item in selected_interests],
        "party": party,
        "party_label": PARTY_LABELS[party],
        "mobility": mobility,
        "mobility_label": MOBILITY_LABELS[mobility],
        "stops": ordered,
        "warnings": warnings,
        "map": {
            "coordinate_system": "WGS-84",
            "display_coordinate_system": "GCJ-02",
            "navigation_provider": "amap",
            "navigation_mode": "walking",
            "tile_url": AMAP_TILE_URL,
            "line_type": "visit-order",
            "mapped_spot_count": mapped_count,
            "total_spot_count": total_spots,
            "coverage_percent": round(mapped_count / total_spots * 100) if total_spots else 0,
            "coverage_note": (
                f"当前 {mapped_count}/{total_spots} 个子景点具备可核验地图点位；"
                "路线连线表示游览顺序，不替代园内步行道路导航。"
            ),
        },
    }
