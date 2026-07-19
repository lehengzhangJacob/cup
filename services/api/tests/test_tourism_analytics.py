from app.tourism_analytics import summarize_rows


def _row(
    tourist_id,
    attraction_name,
    attraction_type,
    satisfaction,
    age=30,
    total_cost=500,
    visit_date=45658,
):
    return {
        "tourist_id": tourist_id,
        "age": age,
        "attraction_name": attraction_name,
        "attraction_type": attraction_type,
        "visit_date": visit_date,
        "stay_duration": 4,
        "ticket_cost": 100,
        "food_cost": 80,
        "total_cost": total_cost,
        "satisfaction": satisfaction,
    }


def test_historical_summary_keeps_scope_and_ordinal_distribution():
    result = summarize_rows(
        [
            _row("U1", "灵山胜境", "历史文化", 4),
            _row("U1", "灵山大佛", "历史文化", 5),
            _row("U2", "自然公园", "自然公园", 3, age=55, total_cost=1600),
        ]
    )

    assert result["rows"] == 3
    assert result["tourists"] == 2
    assert result["attractions"] == 3
    assert result["avg_satisfaction"] == 4.0
    assert [item["count"] for item in result["satisfaction_distribution"]] == [
        0,
        0,
        1,
        1,
        1,
    ]
    assert {item["name"] for item in result["lingshan_samples"]} == {
        "灵山胜境",
        "灵山大佛",
    }
