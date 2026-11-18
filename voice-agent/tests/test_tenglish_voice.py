from app.pipeline import stable_voice_for_language


def test_tenglish_switch_keeps_one_voice():
    voices = {"te-IN": "voice_shared", "en": "voice_shared"}
    assert stable_voice_for_language(voices, "te-IN") == "voice_shared"
    assert stable_voice_for_language(voices, "en") == "voice_shared"


def test_shared_key_wins_over_per_language_ids():
    voices = {"shared": "one_voice", "te-IN": "other", "en": "another"}
    assert stable_voice_for_language(voices, "te-IN") == "one_voice"
    assert stable_voice_for_language(voices, "en") == "one_voice"


def test_bare_language_code_falls_back_to_english_voice():
    voices = {"en": "fallback"}
    assert stable_voice_for_language(voices, "te") == "fallback"
