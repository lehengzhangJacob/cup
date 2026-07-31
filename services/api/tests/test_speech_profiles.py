from app.speech_text import normalize_asr_text
from app.voice_profiles import (
    DEFAULT_VOICE_PROFILE,
    cloud_voice_id,
    normalize_voice_profile,
    public_voice_catalog,
)


def test_legacy_provider_voice_is_mapped_to_paired_profile():
    assert normalize_voice_profile("female") == DEFAULT_VOICE_PROFILE
    assert normalize_voice_profile("tongtong") == DEFAULT_VOICE_PROFILE


def test_voice_catalog_only_exposes_paired_local_cloud_profiles():
    catalog = public_voice_catalog()
    assert len(catalog) == 4
    assert all(item["paired"] for item in catalog)
    assert cloud_voice_id(DEFAULT_VOICE_PROFILE)
    assert sum(item["gender"] == "female" for item in catalog) == 2
    assert sum(item["gender"] == "male" for item in catalog) == 2


def test_local_and_cloud_asr_share_scenic_post_processing():
    assert normalize_asr_text("靈山年花湾梵工") == "灵山拈花湾梵宫"
    assert normalize_asr_text("您好，我是玲玲") == "您好，我是灵灵"
