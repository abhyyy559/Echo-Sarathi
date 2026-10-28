"""Telephony abstraction for placing outbound calls.

``TelephonyClient`` is the interface the dialer depends on; ``TwilioClient``
and ``PlivoClient`` are the production implementations and
``FakeTelephonyClient`` is used in tests and local development without
telephony credentials.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from app.config import Settings

logger = logging.getLogger(__name__)


def mask_phone(phone: Any) -> str:
    """Mask a phone number for logs: all but the last 4 digits hidden.

    Full numbers in logs are PII (M1); debugging rarely needs more than the
    tail to correlate with a contact row.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) <= 4:
        return "****"
    return "*" * (len(digits) - 4) + digits[-4:]


class TelephonyClient(Protocol):
    """Interface for placing an outbound call.

    Returns the provider's id for the call (Twilio CallSid / Plivo request
    uuid). Raises on failure â€” the dialer converts exceptions into per-call
    failures.
    """

    def place_call(self, to: str, call_id: int) -> str:
        ...  # pragma: no cover

    def hangup(self, provider_call_id: str) -> bool:
        """Drop a live leg by the id ``place_call`` returned.

        Returns False when the provider could not be reached; a call that is
        already gone is success, not failure.
        """
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
            # NOTE: no record=/recording_status_callback â€” trial accounts
            # reject recording params with HTTP 400 ("limited parameter
            # access"). Call content is captured by our own pipeline
            # (LiveKit room + transcript rows), so provider recording is
            # redundant for demos; re-add behind a paid-account flag later.
        )
        logger.info("placed twilio call call_id=%s sid=%s to=%s", call_id, call.sid, mask_phone(to))
        return str(call.sid)

    def hangup(self, provider_call_id: str) -> bool:
        from twilio.rest import Client

        client = Client(
            self.settings.twilio_account_sid, self.settings.twilio_auth_token
        )
        try:
            client.calls(provider_call_id).update(status="completed")
        except Exception as exc:  # noqa: BLE001 - already-ended legs are not failures
            if str(getattr(exc, "code", "") or "") == "20003":
                # "Unable to update the object": the leg is already gone.
                return True
            logger.warning("twilio hangup failed call=%s: %s", provider_call_id, exc)
            return False
        return True


class PlivoClient:
    """Production telephony client using the Plivo REST API.

    Plivo's create-call response carries a request uuid, not the final call
    UUID â€” the answer / status webhooks overwrite provider_call_id with the
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
            mask_phone(to),
        )
        return request_uuid or f"PL{call_id:010d}"

    def hangup(self, provider_call_id: str) -> bool:
        from plivo import RestClient

        client = RestClient(self.settings.plivo_auth_id, self.settings.plivo_auth_token)
        try:
            client.calls.delete(provider_call_id)
        except Exception as exc:  # noqa: BLE001 - already-ended legs are not failures
            logger.warning("plivo hangup failed call=%s: %s", provider_call_id, exc)
            return False
        return True


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
        # The carrier fetches this URL itself, so a laptop-local address can
        # never work. Vobiz answers 400 "answer_url parameter is not valid",
        # which reads like a credentials problem; say what it really is.
        if urlsplit(base).hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            raise RuntimeError(
                f"PUBLIC_BASE_URL is {base} — Vobiz cannot reach a loopback answer "
                "webhook. Start a tunnel and point PUBLIC_BASE_URL at it."
            )
        return f"{base}/vobiz/answer?call_id={call_id}"

    def _status_webhook(self, call_id: int) -> str:
        base = self.settings.public_base_url.rstrip("/")
        # The carrier fetches hangup_url itself and signs nothing, so carry
        # call_id in the query: it is the fallback key when the Call-create
        # response had no provider id to store on the row.
        return f"{base}/vobiz/status?call_id={call_id}"

    @staticmethod
    def _error_reason(resp: Any) -> str:
        """Vobiz puts the human-readable cause in {error} (or {message})."""
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 - a non-JSON error still has .text
            return ""
        if isinstance(body, Mapping):
            for key in ("error", "message", "error_message"):
                value = body.get(key)
                if value:
                    return str(value)[:300]
        return ""

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
                    # Without this the campaign only learns a no-answer/busy
                    # outcome when the stale-ringing sweeper reconciles 10
                    # minutes later, so one unanswered contact stalls every
                    # following dial for ten minutes.
                    "hangup_url": self._status_webhook(call_id),
                    "hangup_method": "POST",
                },
            )
            try:
                resp.raise_for_status()
            except Exception as exc:
                logger.warning(
                    "vobiz call-create failed status=%s body=%s",
                    resp.status_code, resp.text[:500],
                )
                reason = self._error_reason(resp) or resp.text[:200] or "no response body"
                if "answer_url" in reason:
                    reason += (
                        " — the carrier could not validate the answer webhook; "
                        "check that PUBLIC_BASE_URL is publicly reachable (restart the tunnel)"
                    )
                raise RuntimeError(
                    f"vobiz refused the call ({resp.status_code}): {reason}"
                ) from exc
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001 â€” non-JSON success is still success
                body = {}
        sid = self._call_id_from_response(body)
        logger.info("placed vobiz call call_id=%s provider_id=%s to=%s", call_id, sid, mask_phone(to))
        return sid or f"VB{call_id:010d}"

    def hangup(self, provider_call_id: str) -> bool:
        import httpx

        settings = self.settings
        url = (
            f"{self._BASE_URL}/api/v1/Account/{settings.vobiz_auth_id}"
            f"/Call/{provider_call_id}/"
        )
        with httpx.Client(timeout=15.0) as client:
            try:
                resp = client.delete(
                    url,
                    headers={
                        "X-Auth-ID": settings.vobiz_auth_id,
                        "X-Auth-Token": settings.vobiz_auth_token,
                        "Accept": "application/json",
                    },
                )
            except Exception as exc:  # noqa: BLE001 - caller can still hang up
                logger.warning("vobiz hangup request failed call=%s: %s", provider_call_id, exc)
                return False
        # 404 = the leg is already gone, which is the outcome we wanted.
        if resp.status_code in (200, 204, 404):
            logger.info("vobiz hangup sent call=%s status=%s", provider_call_id, resp.status_code)
            return True
        logger.warning(
            "vobiz hangup rejected call=%s status=%s body=%s",
            provider_call_id, resp.status_code, resp.text[:200],
        )
        return False


class FakeTelephonyClient:
    """In-memory fake; records placed calls and returns synthetic Sids."""

    def __init__(self) -> None:
        self.placed: list[tuple[str, int]] = []
        self.hung_up: list[str] = []
        self.fail_next = False

    def place_call(self, to: str, call_id: int) -> str:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("fake telephony failure")
        self.placed.append((to, call_id))
        return f"CAfake{call_id:010d}"

    def hangup(self, provider_call_id: str) -> bool:
        self.hung_up.append(provider_call_id)
        return True


#: Ids our clients mint when the provider response carried no real leg id
#: (``VB0000000023``). They exist only in our database, so sending them to a
#: provider API is a guaranteed 404 that hides the actual problem.
_SYNTHETIC_LEG_ID_RE = re.compile(r"^(CAfake\d*|VB\d+|PL\d+)$")


def is_synthetic_leg_id(provider_call_id: Any) -> bool:
    return bool(_SYNTHETIC_LEG_ID_RE.match(str(provider_call_id or "").strip()))


def hangup_provider_call(telephony: TelephonyClient, provider_call_id: Any) -> bool:
    """Best-effort drop of a live leg; never raises.

    Our ``<Stream>`` answer XML keeps the carrier leg alive after the media
    websocket closes, so closing the bridge is not enough to end a call.
    """
    leg_id = str(provider_call_id or "").strip()
    if not leg_id or is_synthetic_leg_id(leg_id):
        return False
    try:
        return bool(telephony.hangup(leg_id))
    except Exception:  # noqa: BLE001 - teardown must not fail the request
        logger.warning("hangup failed for leg %s", leg_id, exc_info=True)
        return False
