from __future__ import annotations

import time

from app.location import SPOT_ANCHORS, location_options, resolve_location


def test_strong_fresh_gps_resolves_nearest_spot():
    spot = SPOT_ANCHORS["LS-FO"]
    result = resolve_location(
        "gps",
        lat=spot["lat"],
        lng=spot["lng"],
        accuracy_m=12,
        timestamp_ms=time.time() * 1000,
    )
    assert result["resolved"] is True
    assert result["confidence"] == "high"
    assert result["spot_id"] == "LS-FO"


def test_weak_gps_returns_candidate_without_claiming_resolution():
    spot = SPOT_ANCHORS["LS-006"]
    result = resolve_location("gps", lat=spot["lat"], lng=spot["lng"], accuracy_m=380)
    assert result["resolved"] is False
    assert result["reason"] == "weak_signal"
    assert result["spot_id"] == "LS-006"
    assert result["requires_confirmation"] is True
    assert [item["mode"] for item in result["fallbacks"]] == ["qr", "wifi", "manual"]


def test_stale_gps_is_not_trusted():
    spot = SPOT_ANCHORS["LS-FG"]
    result = resolve_location(
        "gps",
        lat=spot["lat"],
        lng=spot["lng"],
        accuracy_m=10,
        timestamp_ms=(time.time() - 300) * 1000,
    )
    assert result["resolved"] is False
    assert result["reason"] == "stale_position"


def test_unknown_qr_and_wifi_nodes_do_not_false_positive():
    assert resolve_location("qr", code="BAD-CODE")["resolved"] is False
    assert resolve_location("wifi", code="BAD-NODE")["resolved"] is False


def test_qr_wifi_and_manual_fallbacks_resolve():
    assert resolve_location("qr", code="ls-006")["spot_name"] == "九龙灌浴"
    assert resolve_location("wifi", code="LS-WIFI-BRAHMA")["confidence"] == "medium"
    manual = resolve_location("manual", spot_name="五印坛城")
    assert manual["resolved"] is True
    assert manual["confidence"] == "user_confirmed"


def test_complete_qr_registry_covers_lingshan_and_nianhuawan_children():
    options = location_options()
    codes = {item["spot_id"] for item in options["points"]}

    assert "LS-011" in codes
    assert "NH-006" in codes
    assert resolve_location("qr", code="NH-006")["spot_name"] == "鹿鸣谷"
