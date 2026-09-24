"""Telephony abstraction for placing outbound calls.

``TelephonyClient`` is the interface the dialer depends on; ``TwilioClient``
and ``PlivoClient`` are the production implementations and
``FakeTelephonyClient`` is used in tests and local development without
telephony credentials.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Protocol

from app.config import Settings

logger = logging.getLogger(__name__)


class TelephonyClient(Protocol):
    """Interface for placing an outbound call.

    Returns the provider's id for the call (Twilio CallSid / Plivo request
    uuid). Raises on failure — the dialer converts exceptions into per-call
    failures.
    """

    def place_call(self, to: str, call_id: int) -> str:
        ...  # pragma: no cover


class TwilioClient:
    """Production telephony client using the Twilio REST API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _voice_webhook(self, call_id: int) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/twilio/voice?call_id={call_id}"

    def place_call(self, to: str, call_id: int) -> str:
        from twilio.rest import Client  # lazy import keeps tests light

        settings = self.settings
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        base = settings.public_base_url.rstrip("/")
        call = client.calls.create(
            to=to,
            from_=settings.twilio_phone_number,
            url=self._voice_webhook(call_id),
            method="POST",
            status_callback=f"{base}/twilio/status",
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            # NOTE: no record=/recording_status_callback — trial accounts
            # reject recording params with HTTP 400 ("limited parameter
            # access"). Call content is captured by our own pipeline
            # (LiveKit room + transcript rows), so provider recording is
            # redundant for demos; re-add behind a paid-account flag later.
        )
        logger.info("placed twilio call call_id=%s sid=%s to=%s", call_id, call.sid, to)
        return str(call.sid)


class PlivoClient:
    """Production telephony client using the Plivo REST API.

    Plivo's create-call response carries a request uuid, not the final call
    UUID — the answer / status webhooks overwrite provider_call_id with the
    real CallUUID (see routers/plivo.py).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _answer_webhook(self, call_id: int) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/plivo/voice?call_id={call_id}"

    def _status_webhook(self, call_id: int) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/plivo/status?call_id={call_id}"

    @staticmethod
    def _request_uuid(response: Any) -> str:
        if isinstance(response, dict):
            return str(response.get("request_uuid") or "")
        return str(getattr(response, "request_uuid", "") or "")

    def place_call(self, to: str, call_id: int) -> str:
        from plivo import RestClient  # lazy import keeps tests light

        settings = self.settings
        client = RestClient(settings.plivo_auth_id, settings.plivo_auth_token)
        response = client.calls.create(
            to=to,
            from_=settings.plivo_phone_number,
            answer_url=self._answer_webhook(call_id),
            answer_method="POST",
            ring_url=self._status_webhook(call_id),
            ring_method="POST",
            hangup_url=self._status_webhook(call_id),
            hangup_method="POST",
        )
        request_uuid = self._request_uuid(response)
        logger.info(
            "placed plivo call call_id=%s request_uuid=%s to=%s",
            call_id,
            request_uuid,
            to,
        )
        return request_uuid or f"PL{call_id:010d}"


class VobizClient:
    """Production telephony client using the Vobiz REST API.

    Outbound calls: POST /api/v1/Account/{auth_id}/Call/ with
    X-Auth-ID / X-Auth-Token headers; the answer webhook returns Voice XML
    whose <Stream> element bridges bidirectional mu-law 8kHz audio to our
    media websocket (see routers/vobiz.py).
    """

    _BASE_URL = "https://api.vobiz.ai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _answer_webhook(self, call_id: int) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/vobiz/answer?call_id={call_id}"

    @staticmethod
    def _call_id_from_response(response: Any) -> str:
        """Accept the several id shapes a Call-create response may carry."""
        if isinstance(response, Mapping):
            for key in ("callSid", "CallSid", "call_sid", "callId", "call_id",
                        "request_uuid", "call_uuid", "sid", "id"):
                value = response.get(key)
                if value:
                    return str(value)
            data = response.get("data")
            if isinstance(data, Mapping):
                return VobizClient._call_id_from_response(data)
            return ""
        for attr in ("call_sid", "callSid", "request_uuid", "sid"):
            value = getattr(response, attr, None)
            if value:
                return str(value)
        return ""

    def place_call(self, to: str, call_id: int) -> str:
        import httpx

        settings = self.settings
        url = f"{self._BASE_URL}/api/v1/Account/{settings.vobiz_auth_id}/Call/"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                headers={
                    "X-Auth-ID": settings.vobiz_auth_id,
                    "X-Auth-Token": settings.vobiz_auth_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "from": settings.vobiz_phone_number,
                    "to": to,
                    "answer_url": self._answer_webhook(call_id),
                    "answer_method": "POST",
                },
            )
            try:
                resp.raise_for_status()
            except Exception:
                logger.warning(
                    "vobiz call-create failed status=%s body=%s",
                    resp.status_code, resp.text[:500],
                )
                raise
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001 — non-JSON success is still success
                body = {}
        sid = self._call_id_from_response(body)
        logger.info("placed vobiz call call_id=%s provider_id=%s to=%s", call_id, sid, to)
        return sid or f"VB{call_id:010d}"


class FakeTelephonyClient:
    """In-memory fake; records placed calls and returns synthetic Sids."""

    def __init__(self) -> None:
        self.placed: list[tuple[str, int]] = []
        self.fail_next = False

    def place_call(self, to: str, call_id: int) -> str:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("fake telephony failure")
        self.placed.append((to, call_id))
        return f"CAfake{call_id:010d}"
