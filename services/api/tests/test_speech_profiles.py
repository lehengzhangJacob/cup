from app.speech_text import normalize_asr_text
from app.voice_profiles import (
    DEFAULT_CLOUD_VOICE,
    DEFAULT_VOICE_PROFILE,
    normalize_cloud_voice,
    normalize_voice_profile,
    public_cloud_voice_catalog,
    public_local_voice_catalog,
    public_voice_catalog,
)


def test_legacy_provider_voice_is_mapped_to_local_profile():
    assert normalize_voice_profile("female") == DEFAULT_VOICE_PROFILE
    assert normalize_voice_profile("tongtong") == "lingyue_female_v1"
    assert normalize_voice_profile("male") == "lingyun_male_v1"


def test_local_and_cloud_voice_catalogs_are_independent():
    local_catalog = public_local_voice_catalog()
    cloud_catalog = public_cloud_voice_catalog()
    assert public_voice_catalog() == local_catalog
    assert len(local_catalog) == 4
    assert sum(item["gender"] == "female" for item in local_catalog) == 2
    assert sum(item["gender"] == "male" for item in local_catalog) == 2
    assert {item["id"] for item in cloud_catalog} >= {"female", "male"}
    assert normalize_cloud_voice("female") == "female"
    assert normalize_cloud_voice("not-a-system-voice") == DEFAULT_CLOUD_VOICE


def test_local_and_cloud_asr_share_scenic_post_processing():
    assert normalize_asr_text("靈山年花湾梵工") == "灵山拈花湾梵宫"
    assert normalize_asr_text("您好，我是玲玲") == "您好，我是灵灵"
