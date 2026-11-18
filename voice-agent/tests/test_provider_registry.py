from app.config import Settings, reset_settings_cache
from app.providers.base import STTProvider
from app.providers.registry import (
    ProviderRole,
    ProviderSpec,
    _SPECS,
    register_provider,
    select_provider,
)


class FakeSTT:
    name = "fake"

    def build(self):
        return object()


def test_select_provider_by_role_language_and_env(monkeypatch):
    _SPECS.clear()
    register_provider(ProviderSpec("sarvam", ProviderRole.STT, ("te-IN", "hi-IN")))
    register_provider(ProviderSpec("deepgram", ProviderRole.STT, ("en",)))
    monkeypatch.setenv("STT_PROVIDER", "")
    monkeypatch.setenv("STT_PROVIDER_TE", "sarvam")
    reset_settings_cache()
    settings = Settings.from_env()
    assert select_provider(ProviderRole.STT, "te-IN", settings).spec.name == "sarvam"
    assert select_provider(ProviderRole.STT, "en", settings).spec.name == "deepgram"


def test_fake_provider_satisfies_protocol():
    assert isinstance(FakeSTT(), STTProvider)
