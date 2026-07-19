from app.vision_analysis import parse_vision_observation, vision_prompt


def test_vision_candidates_are_restricted_to_local_attraction_catalog():
    parsed = parse_vision_observation(
        '{"summary":"画面中有巨大佛像",'
        '"candidates":[{"name":"灵山大佛","confidence":0.93,"evidence":"佛像"},'
        '{"name":"不存在的景点","confidence":0.99}]}'
    )

    assert parsed["confidence"] == "high"
    assert parsed["requires_confirmation"] is False
    assert [item["name"] for item in parsed["candidates"]] == ["灵山大佛"]
    assert parsed["candidates"][0]["id"] == "LS-011"


def test_prose_candidate_requires_visitor_confirmation():
    parsed = parse_vision_observation("图片可能是灵山梵宫，室内有金色装饰。")

    assert parsed["confidence"] == "medium"
    assert parsed["requires_confirmation"] is True
    assert parsed["candidates"][0]["name"] == "灵山梵宫"


def test_vision_prompt_requires_structured_candidates():
    prompt = vision_prompt()

    assert "只返回 JSON" in prompt
    assert "灵山大佛" in prompt
