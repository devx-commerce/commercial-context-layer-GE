"""FastAPI app wiring (build spec section 16).

/oauth/* and /webhooks/slack/events are publicly reachable but validate their
own OAuth state / Slack signature. /internal/* requires a valid Google-signed
OIDC token from the configured Cloud Scheduler service account. No route here
logs request or response bodies.
"""

import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth.gmail_oauth import OAuthError, build_authorization_url, handle_callback
from app.auth.scheduler_auth import require_scheduler_auth
from app.config_loader import ConfigError, load_config_and_users
from app.jobs import backfill_domain, gmail_poll, pending_index, reindex_domain
from app.sources import slack_client
from app.sources.slack_ingestion import handle_event_payload, verify_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Commercial Context Layer POC")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/oauth/gmail/start")
def oauth_gmail_start() -> RedirectResponse:
    return RedirectResponse(build_authorization_url())


@app.get("/oauth/gmail/callback")
def oauth_gmail_callback(code: str = Query(...), state: str = Query(...)) -> JSONResponse:
    try:
        email = handle_callback(code, state)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({"status": "onboarded", "email": email})


@app.post("/webhooks/slack/events")
async def slack_events(request: Request) -> JSONResponse:
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_signature(raw_body, timestamp, signature, slack_client.signing_secret()):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()

    # Slack's URL-verification handshake doesn't touch config at all — it must
    # be answered before any config load, not just before a successful one.
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge")})

    try:
        config, _, _ = load_config_and_users()
    except ConfigError:
        logger.exception("slack_event_dropped_invalid_config")
        return JSONResponse({})

    response_body = handle_event_payload(payload, config)
    return JSONResponse(response_body or {})


@app.post("/internal/poll-gmail", dependencies=[Depends(require_scheduler_auth)])
def poll_gmail() -> dict:
    gmail_poll.run()
    return {"status": "ok"}


@app.post("/internal/process-pending", dependencies=[Depends(require_scheduler_auth)])
def process_pending() -> dict:
    pending_index.process_all_pending()
    return {"status": "ok"}


@app.post("/internal/reindex-domain", dependencies=[Depends(require_scheduler_auth)])
def reindex(domain: str = Query(...)) -> dict:
    try:
        return reindex_domain.run(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/internal/backfill-domain", dependencies=[Depends(require_scheduler_auth)])
def backfill(domain: str = Query(...)) -> dict:
    try:
        return backfill_domain.run(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
