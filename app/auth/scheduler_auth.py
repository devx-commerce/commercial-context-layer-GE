"""FastAPI dependency guarding /internal/* routes.

Cloud Scheduler calls these with a Google-signed OIDC identity token. We verify
the token's signature/issuer/expiry and audience (the Cloud Run service URL),
then check the email claim matches the configured scheduler service account —
this is the only thing that may call /internal/* (build spec section 16).
"""

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.settings import require, settings

_google_request = google_requests.Request()


def require_scheduler_auth(authorization: str = Header(default="")) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer "):]

    audience = require(settings.oidc_audience, "OIDC_AUDIENCE")
    expected_email = require(settings.scheduler_service_account_email, "SCHEDULER_SERVICE_ACCOUNT_EMAIL")

    try:
        claims = id_token.verify_oauth2_token(token, _google_request, audience=audience)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid OIDC token")

    if claims.get("email") != expected_email or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="unauthorized caller")
