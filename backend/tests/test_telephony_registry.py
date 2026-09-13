"""Telephony provider registry: who gets built, when the dialer is allowed to run."""
from app.config import Settings
from app.main import _build_telephony, _should_run_dialer
from app.services.calls_service import PLIVO_STATUS_MAP
from app.services.telephony import FakeTelephonyClient, PlivoClient, TwilioClient

from conftest import make_settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "dialer_enabled": True,
        "twilio_account_sid": "",
        "twilio_auth_token": "",
        "plivo_auth_id": "",
        "plivo_auth_token": "",
    }
    defaults.update(overrides)
    return make_settings(**defaults)


def test_plivo_creds_build_plivo_client():
    settings = _settings(plivo_auth_id="PA", plivo_auth_token="PT")
    assert isinstance(_build_telephony(settings), PlivoClient)


def test_twilio_creds_build_twilio_client():
    settings = _settings(twilio_account_sid="AC", twilio_auth_token="AT")
    assert isinstance(_build_telephony(settings), TwilioClient)


def test_both_creds_prefer_plivo():
    settings = _settings(
        twilio_account_sid="AC",
        twilio_auth_token="AT",
        plivo_auth_id="PA",
        plivo_auth_token="PT",
    )
    assert isinstance(_build_telephony(settings), PlivoClient)


def test_no_creds_build_fake():
    assert isinstance(_build_telephony(_settings()), FakeTelephonyClient)


def test_explicit_plivo_without_creds_is_fake_even_with_twilio():
    settings = _settings(
        telephony_provider="plivo", twilio_account_sid="AC", twilio_auth_token="AT"
    )
    assert isinstance(_build_telephony(settings), FakeTelephonyClient)


def test_explicit_twilio_with_creds():
    settings = _settings(
        telephony_provider="twilio", twilio_account_sid="AC", twilio_auth_token="AT"
    )
    assert isinstance(_build_telephony(settings), TwilioClient)


def test_should_run_dialer_with_plivo_creds():
    settings = _settings(plivo_auth_id="PA", plivo_auth_token="PT")
    assert _should_run_dialer(settings) is True


def test_should_run_dialer_explicit_plivo_missing_creds():
    settings = _settings(
        telephony_provider="plivo", twilio_account_sid="AC", twilio_auth_token="AT"
    )
    assert _should_run_dialer(settings) is False


def test_should_run_dialer_no_creds():
    assert _should_run_dialer(_settings()) is False


def test_should_run_dialer_disabled_flag_wins():
    settings = _settings(dialer_enabled=False, plivo_auth_id="PA", plivo_auth_token="PT")
    assert _should_run_dialer(settings) is False


def test_provider_presence_plivo_booleans():
    assert make_settings().provider_presence["plivo"] is False
    assert (
        _settings(plivo_auth_id="PA", plivo_auth_token="PT").provider_presence["plivo"]
        is True
    )


def test_plivo_status_map_spelling():
    assert PLIVO_STATUS_MAP["ringing"] == "ringing"
    assert PLIVO_STATUS_MAP["in-progress"] == "in_progress"
    assert PLIVO_STATUS_MAP["no-answer"] == "no_answer"
    assert PLIVO_STATUS_MAP["busy"] == "busy"
    assert PLIVO_STATUS_MAP["canceled"] == "canceled"
    assert PLIVO_STATUS_MAP["completed"] == "completed"