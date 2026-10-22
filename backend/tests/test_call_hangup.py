"""Provider hangup on call end: the leg must drop when the agent says goodbye.

The media bridge's ``<Stream>`` answer keeps the carrier leg alive after the
conversation is over, so ending a call takes an explicit hangup. These tests
pin the guardrails around that request - only real leg ids, room name derived
per call kind, and the internal endpoint the worker calls.
"""
from __future__ import annotations

from app.models import Call
from app.services.call_teardown import hangup_carrier_leg, room_for_call
from app.services.telephony import (
    FakeTelephonyClient,
    hangup_provider_call,
    is_synthetic_leg_id,
)

INTERNAL = {"X-Internal-Token": "test_internal_token"}


class _RaisingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def hangup(self, provider_call_id: str) -> bool:
        self.calls.append(provider_call_id)
        raise RuntimeError("provider down")


def test_synthetic_leg_ids_are_not_sent_to_the_provider() -> None:
    for leg in ("CAfake0000000023", "VB0000000023", "PL0000000023"):
        assert is_synthetic_leg_id(leg)
    assert not is_synthetic_leg_id("")
    assert not is_synthetic_leg_id("b6a1f0c2-9c1e-4b2a-9b3f-1d2e3f4a5b6c")


def test_hangup_provider_call_swallows_provider_errors() -> None:
    client = _RaisingClient()
    assert hangup_provider_call(client, "b6a1-uuid") is False
    assert client.calls == ["b6a1-uuid"]


def test_hangup_provider_call_skips_synthetic_ids() -> None:
    client = FakeTelephonyClient()
    assert hangup_provider_call(client, "VB0000000023") is False
    assert client.hung_up == []


def test_hangup_carrier_leg_needs_a_leg_id() -> None:
    client = FakeTelephonyClient()
    assert hangup_carrier_leg(client, Call(id=7, provider_call_id=None), reason="test") is False
    assert client.hung_up == []
    assert hangup_carrier_leg(client, Call(id=7, provider_call_id="real-uuid"), reason="test") is True
    assert client.hung_up == ["real-uuid"]


def test_room_for_call_only_names_phone_rooms() -> None:
    assert room_for_call(Call(id=7, kind="campaign")) == "phone-7"
    assert room_for_call(Call(id=7, kind="playground")) is None


def test_internal_hangup_endpoint_uses_the_worker_room(client, session_factory, monkeypatch):
    seen: dict[str, object] = {}

    def _fake_close(settings, telephony, call, *, room_name=None, reason):
        seen["room"] = room_name
        seen["reason"] = reason
        seen["call_id"] = call.id
        return {"hangup": True, "room": room_name, "room_closed": True}

    monkeypatch.setattr("app.routers.internal.close_call_media", _fake_close)
    with session_factory() as db:
        call = Call(status="completed", provider_call_id="real-uuid")
        db.add(call)
        db.commit()
        call_id = call.id

    resp = client.post(
        f"/internal/calls/{call_id}/hangup",
        json={"room": "phone-%d" % call_id},
        headers=INTERNAL,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["hangup"] is True
    assert seen["room"] == f"phone-{call_id}"
    assert seen["reason"] == "agent_end_call"
    assert seen["call_id"] == call_id
