"""Built-in providers are registered and the pipeline records why it chose one."""

from app.pipeline import ProviderBundle, _register_builtin_providers
from app.providers.registry import ProviderRole, ProviderSpec, _SPECS, register_provider


def test_registry_exposes_existing_providers():
    _SPECS.clear()
    register_provider(ProviderSpec("sarvam", ProviderRole.STT, ("te-IN", "hi-IN")))
    register_provider(ProviderSpec("deepgram", ProviderRole.STT, ("en",)))
    register_provider(ProviderSpec("sarvam_bulbul", ProviderRole.TTS, ("te-IN",)))
    register_provider(ProviderSpec("cartesia", ProviderRole.TTS, ("en",)))
    assert ("stt", "sarvam") in _SPECS
    assert ("tts", "cartesia") in _SPECS


def test_builtin_registration_and_bundle_fields():
    _register_builtin_providers()
    assert ("stt", "sarvam") in _SPECS
    assert ("tts", "cartesia") in _SPECS
    bundle = ProviderBundle(stt=object(), llm=object(), tts=object())
    assert bundle.stt_provider_selection == "default"
    assert bundle.tts_provider_selection == "default"
