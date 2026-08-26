"""Slack Events API webhook handling (build spec section 11).

Signature verification happens against the raw body before any JSON parsing.
Like Gmail ingestion, this module never calls Gemini directly: it only writes
approved evidence to GCS and queues a pending operation for the 5-minute
process-pending job to act on. Attachment bytes are always fetched later by
that job (never inline here) — one code path instead of two, and no risk of
missing Slack's short webhook-ack window.
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Optional

from app.models import Config, PendingOperation
from app.normalization import slack_document
from app.sources import mime, slack_client
from app.storage import gcs

logger = logging.getLogger(__name__)

_SIGNATURE_TOLERANCE_SECONDS = 5 * 60
_EVENT_ID_TTL_SECONDS = 10 * 60
_seen_event_ids: Dict[str, float] = {}


def verify_signature(raw_body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
    try:
        if abs(time.time() - float(timestamp)) > _SIGNATURE_TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    base = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    computed = "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _is_duplicate_event(event_id: str) -> bool:
    now = time.monotonic()
    for stale_id, expiry in list(_seen_event_ids.items()):
        if expiry < now:
            del _seen_event_ids[stale_id]
    if event_id in _seen_event_ids:
        return True
    _seen_event_ids[event_id] = now + _EVENT_ID_TTL_SECONDS
    return False


def _message_path(account_domain: str, channel_id: str, document_id: str) -> str:
    # Channel ID is part of the layout so ACL resync/reindex jobs can find every
    # document of one channel by prefix alone.
    return f"approved/{account_domain}/slack/{channel_id}/{document_id}/message.html"


def _queue_upsert(document_id: str, path: str) -> None:
    gcs.write_pending_operation(
        PendingOperation(operation="upsert", document_id=document_id, content_uri=gcs.content_uri(path))
    )


def _handle_message(event: dict, team_id: str, config: Config) -> None:
    channel_id = event.get("channel")
    channel = config.slack_channels.get(channel_id) if channel_id else None
    if channel is None:
        return  # not whitelisted; discard silently per section 11 point 6

    message_ts = event.get("ts")
    if not message_ts:
        return

    author_name = slack_client.resolve_user_name(event["user"]) if event.get("user") else "unknown"
    resolved_text = slack_client.resolve_mentions(event.get("text", ""))
    sent_at = _ts_to_iso(message_ts)

    document = slack_document.build(
        workspace_id=team_id,
        channel_id=channel_id,
        channel_name=channel.name,
        message_ts=message_ts,
        author_name=author_name,
        sent_at=sent_at,
        thread_ts=event.get("thread_ts"),
        resolved_text=resolved_text,
    )
    path = _message_path(channel.account_domain, channel_id, document.document_id)
    gcs.write_bytes(path, document.html.encode("utf-8"), content_type="text/html")
    _queue_upsert(document.document_id, path)

    for file_obj in event.get("files", []) or []:
        ext = mime.extension_for_mime(file_obj.get("mimetype", ""))
        if ext is None:
            continue
        gcs.write_pending_operation(
            PendingOperation(
                operation="fetch_slack_attachment",
                document_id=f"pending:{file_obj['id']}",
                slack_file_id=file_obj["id"],
                slack_channel_id=channel_id,
                parent_document_id=document.document_id,
            )
        )


def _handle_message_changed(event: dict, team_id: str, config: Config) -> None:
    edited = event.get("message")
    if not edited:
        return
    synthetic_event = {**edited, "channel": event.get("channel")}
    _handle_message(synthetic_event, team_id, config)


def _handle_message_deleted(event: dict, team_id: str, config: Config) -> None:
    channel_id = event.get("channel")
    channel = config.slack_channels.get(channel_id) if channel_id else None
    deleted_ts = event.get("deleted_ts")
    if channel is None or not deleted_ts:
        return
    document_id = slack_document.compute_document_id(team_id, channel_id, deleted_ts)
    path = _message_path(channel.account_domain, channel_id, document_id)
    gcs.write_pending_operation(
        PendingOperation(operation="delete", document_id=document_id, content_uri=gcs.content_uri(path))
    )


def _queue_channel_acl_resync(channel_id: Optional[str], config: Config) -> None:
    """A membership change in a whitelisted channel re-derives the ACL of every
    document in that channel via the pending queue (process-pending job)."""
    if not channel_id or channel_id not in config.slack_channels:
        return
    try:
        gcs.write_pending_operation(
            PendingOperation(
                operation="resync_channel_acl",
                document_id=f"resync:{channel_id}",
                slack_channel_id=channel_id,
            )
        )
    except Exception:
        logger.exception("slack_membership_resync_queue_failed")


def _ts_to_iso(ts: str) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def handle_event_payload(payload: dict, config: Config) -> Optional[dict]:
    """Returns a JSON-able dict to respond with, or None when a plain 200 ack is
    all that's needed. Callers must answer the URL-verification handshake
    (payload["type"] == "url_verification") before calling this — it doesn't
    depend on config and shouldn't be gated behind a config load succeeding."""
    if payload.get("type") != "event_callback":
        return None

    if _is_duplicate_event(payload.get("event_id", "")):
        return None

    event = payload.get("event", {})
    event_type = event.get("type")
    subtype = event.get("subtype")
    team_id = payload.get("team_id", "")

    if event_type in ("member_joined_channel", "member_left_channel"):
        _queue_channel_acl_resync(event.get("channel"), config)
        return None

    if event_type != "message":
        return None
    if subtype in ("channel_join", "channel_leave", "bot_message"):
        return None

    try:
        if subtype == "message_changed":
            _handle_message_changed(event, team_id, config)
        elif subtype == "message_deleted":
            _handle_message_deleted(event, team_id, config)
        else:
            _handle_message(event, team_id, config)
    except Exception:
        logger.exception("slack_event_processing_failed")
    return None
