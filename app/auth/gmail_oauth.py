"""Gmail OAuth onboarding (build spec section 9).

`state` is an HMAC-signed, expiring value (10-minute TTL) — no PKCE. PKCE mainly
protects public clients that can't hold a secret; this is a server-side flow
that already holds a client secret via Secret Manager, so PKCE would add
ceremony without adding real protection here. Note the state is not tracked as
single-use server-side (that would need persisted state outside the strict
storage contract) — the short expiry is the replay defense.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app import config_loader
from app.config_loader import ConfigError
from app.models import UserRecord
from app.settings import require, settings
from app.sources import gmail_client, gmail_ingestion
from app.storage import secret_manager

logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 10 * 60
_google_request = google_requests.Request()


class OAuthError(Exception):
    pass


def _signing_key() -> bytes:
    secret_name = require(settings.oauth_state_signing_secret, "OAUTH_STATE_SIGNING_SECRET")
    return secret_manager.access_latest(secret_name).encode("utf-8")


def _create_state() -> str:
    payload = json.dumps({"nonce": secrets.token_urlsafe(16), "exp": int(time.time()) + _STATE_TTL_SECONDS})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(_signing_key(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_state(state: str) -> bool:
    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(_signing_key(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return False
    return int(payload.get("exp", 0)) >= int(time.time())


def build_authorization_url() -> str:
    client = gmail_client.oauth_client_config()
    params = {
        "client_id": client["client_id"],
        "redirect_uri": require(settings.gmail_oauth_redirect_uri, "GMAIL_OAUTH_REDIRECT_URI"),
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": _create_state(),
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _upsert_new_user(email: str, gmail_secret_resource_name: str) -> None:
    def mutate(existing: Optional[dict]) -> dict:
        if existing is None:
            return UserRecord(gmail_secret=gmail_secret_resource_name).model_dump()
        existing["gmail_secret"] = gmail_secret_resource_name
        return existing

    try:
        config_loader.upsert_user_record(email, mutate)
    except ConfigError as exc:
        raise OAuthError(str(exc)) from exc


def handle_callback(code: str, state: str) -> str:
    """Runs the full callback flow (build spec section 9, steps 1-8) and returns
    the onboarded email. Raises OAuthError on any verification failure."""
    if not _verify_state(state):
        raise OAuthError("invalid or expired state")

    client = gmail_client.oauth_client_config()
    token_response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": require(settings.gmail_oauth_redirect_uri, "GMAIL_OAUTH_REDIRECT_URI"),
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    ).json()

    if "error" in token_response:
        raise OAuthError(f"token exchange failed: {token_response['error']}")

    refresh_token = token_response.get("refresh_token")
    if not refresh_token:
        raise OAuthError("no refresh token returned; revoke prior grant at myaccount.google.com and retry")

    try:
        claims = google_id_token.verify_oauth2_token(
            token_response["id_token"], _google_request, audience=client["client_id"]
        )
    except ValueError as exc:
        raise OAuthError(f"invalid id_token: {exc}") from exc

    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified"):
        raise OAuthError("email not present or not verified")

    domain = email.split("@", 1)[1]
    config = config_loader.get_config()
    internal_domains = {d.lower() for d in config.internal_domains}
    if domain not in internal_domains:
        raise OAuthError(f"email domain {domain!r} is not in internal_domains")

    hosted_domain = claims.get("hd")
    if hosted_domain and hosted_domain.lower() != domain:
        raise OAuthError("hosted domain claim does not match email domain")

    secret_id = "gmail-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
    resource_name = secret_manager.get_or_create_user_secret(secret_id)
    secret_manager.add_version(resource_name, refresh_token)

    _upsert_new_user(email, resource_name)

    try:
        gmail_ingestion.run_initial_scan(email, resource_name, config)
    except Exception:
        logger.exception("gmail_initial_scan_failed_for_new_user")

    return email
