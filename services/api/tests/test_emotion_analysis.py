from app.emotion_analysis import analyze_text, fuse_analysis, parse_model_output


def test_text_analysis_extracts_service_aspects_and_rating_anchor():
    result = analyze_text("讲解很清楚，但是九龙灌浴排队太久了", rating=2)

    assert result["sentiment"] == "negative"
    assert result["valence"] < 0
    names = {item["name"] for item in result["aspects"]}
    assert "讲解内容" in names
    assert "排队与客流" in names


def test_text_analysis_does_not_treat_negated_praise_as_positive():
    result = analyze_text("讲解不清楚，回答也不准确，我很不满意")

    assert result["sentiment"] == "negative"
    assert result["valence"] < 0
    assert "满意" not in result["evidence"]


def test_model_output_parser_accepts_json_and_answer_tags():
    parsed = parse_model_output(
        {"emotion": "happy", "confidence": 0.82, "scores": {"happy": 0.82}}
    )
    assert parsed["emotion"] == "happy"
    assert parsed["confidence"] == 0.82

    parsed = parse_model_output("<think>voice and face agree</think><answer>angry</answer>")
    assert parsed["emotion"] == "angry"

    parsed = parse_model_output(
        'startup log\n{"emotion":"happy","scores":{"happy":0.9},"confidence":0.9}'
    )
    assert parsed["emotion"] == "happy"
    assert parsed["scores"]["happy"] == 0.9


def test_fear_is_not_automatically_treated_as_dissatisfaction():
    text = analyze_text("", rating=None)
    result = fuse_analysis(
        text,
        {"emotion": "fear", "confidence": 0.95, "scores": {"fear": 0.95}},
    )

    assert result["emotion"] == "fear"
    assert result["sentiment"] == "neutral"
    assert result["estimated_satisfaction"] == 3.0
