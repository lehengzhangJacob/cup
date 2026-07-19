from app.avatar_reaction import avatar_reaction


def test_negative_text_signal_gets_careful_response():
    reaction = avatar_reaction(sentiment="negative", confidence=0.7)

    assert reaction["id"] == "care"
    assert reaction["expression"] == "gentle"
    assert reaction["voice_speed"] < 1
    assert reaction["prefix"]


def test_fear_is_comforted_without_being_labeled_a_complaint():
    reaction = avatar_reaction(emotion="fear", sentiment="neutral", confidence=0.9)

    assert reaction["id"] == "comfort"
    assert reaction["reason"] == "fear"


def test_happy_signal_drives_smile_response():
    reaction = avatar_reaction(emotion="happy", sentiment="positive")

    assert reaction["id"] == "celebrate"
    assert reaction["expression"] == "smile"
    assert reaction["voice_speed"] > 1
