"""Telephony provider registry: who gets built, when the dialer is allowed to run."""
from app.config import Settings
from app.main import _build_telephony, _should_run_dialer
from app.services.telephony import FakeTelephonyClient, TwilioClient, VobizClient

from conftest import make_settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "dialer_enabled": True,
        "twilio_account_sid": "",
        "twilio_auth_token": "",
        "vobiz_auth_id": "",
        "vobiz_auth_token": "",
    }
    defaults.update(overrides)
    return make_settings(**defaults)


def test_twilio_creds_build_twilio_client():
    settings = _settings(twilio_account_sid="AC", twilio_auth_token="AT")
    assert isinstance(_build_telephony(settings), TwilioClient)


def test_vobiz_creds_build_vobiz_client():
    settings = _settings(vobiz_auth_id="VA", vobiz_auth_token="VT")
    assert isinstance(_build_telephony(settings), VobizClient)


def test_auto_select_prefers_twilio_when_both_credentials_exist():
    settings = _settings(
        twilio_account_sid="AC",
        twilio_auth_token="AT",
        vobiz_auth_id="VA",
        vobiz_auth_token="VT",
    )
    assert isinstance(_build_telephony(settings), TwilioClient)


def test_no_creds_build_fake():
    assert isinstance(_build_telephony(_settings()), FakeTelephonyClient)


def test_explicit_twilio_without_creds_is_fake_even_with_vobiz():
    settings = _settings(
        telephony_provider="twilio", vobiz_auth_id="VA", vobiz_auth_token="VT"
    )
    assert isinstance(_build_telephony(settings), FakeTelephonyClient)


def test_explicit_twilio_with_creds():
    settings = _settings(
        telephony_provider="twilio", twilio_account_sid="AC", twilio_auth_token="AT"
    )
    assert isinstance(_build_telephony(settings), TwilioClient)


def test_explicit_vobiz_with_creds():
    settings = _settings(
        telephony_provider="vobiz", vobiz_auth_id="VA", vobiz_auth_token="VT"
    )
    assert isinstance(_build_telephony(settings), VobizClient)


def test_should_run_dialer_with_vobiz_creds():
    settings = _settings(vobiz_auth_id="VA", vobiz_auth_token="VT")
    assert _should_run_dialer(settings) is True


def test_should_run_dialer_explicit_vobiz_missing_creds():
    settings = _settings(
        telephony_provider="vobiz", twilio_account_sid="AC", twilio_auth_token="AT"
    )
    assert _should_run_dialer(settings) is False


def test_should_run_dialer_no_creds():
    assert _should_run_dialer(_settings()) is False


def test_should_run_dialer_disabled_flag_wins():
    settings = _settings(dialer_enabled=False, vobiz_auth_id="VA", vobiz_auth_token="VT")
    assert _should_run_dialer(settings) is False


def test_provider_presence_twilio_and_vobiz_booleans():
    assert make_settings().provider_presence["twilio"] is False
    assert make_settings().provider_presence["vobiz"] is False
    settings = _settings(vobiz_auth_id="VA", vobiz_auth_token="VT")
    assert settings.provider_presence["vobiz"] is True
    assert settings.provider_presence["twilio"] is False
