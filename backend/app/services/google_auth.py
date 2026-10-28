"""Google Sign-In: verify the ID token minted by Google Identity Services.

The browser obtains a signed ID token ("credential") from Google and posts it
to the API. Verification checks the signature against Google's rotating public
keys, the audience (our client id), expiry, and issuer.
"""
from __future__ import annotations

from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleTokenError(Exception):
    """Raised when a Google credential is missing, expired or forged."""


def verify_google_credential(credential: str, client_id: str) -> dict[str, Any]:
    """Return verified Google claims, or raise ``GoogleTokenError``."""
    try:
        claims = id_token.verify_oauth2_token(
            credential, google_requests.Request(), client_id
        )
    except ValueError as exc:
        raise GoogleTokenError(str(exc)) from exc
    if not claims.get("sub"):
        raise GoogleTokenError("Google credential has no subject")
    if not claims.get("email") or not claims.get("email_verified"):
        raise GoogleTokenError("Google account has no verified email")
    return claims
