"""Thin Gmail API wrapper. Builds a per-user, read-only service from the refresh
token stored under that user's Secret Manager resource (state/users.json ->
gmail_secret). The OAuth client id/secret used to refresh live in the Secret
Manager resource named by settings.gmail_oauth_client_secret (JSON:
{"client_id": "...", "client_secret": "..."}).
"""

import json
from typing import Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.settings import require, settings
from app.storage import secret_manager

_METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID", "In-Reply-To", "References"]

_oauth_client: Optional[Dict[str, str]] = None


def oauth_client_config() -> Dict[str, str]:
    """{"client_id": ..., "client_secret": ...} for the Gmail OAuth web client,
    read once from the Secret Manager resource named by settings.gmail_oauth_client_secret."""
    global _oauth_client
    if _oauth_client is None:
        secret_name = require(settings.gmail_oauth_client_secret, "GMAIL_OAUTH_CLIENT_SECRET")
        raw = secret_manager.access_latest(secret_name)
        _oauth_client = json.loads(raw)
    return _oauth_client


def get_service_for_user(gmail_secret_resource_name: str):
    refresh_token = secret_manager.access_latest(gmail_secret_resource_name)
    client = oauth_client_config()
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_message_ids(service, query: str) -> List[str]:
    ids: List[str] = []
    request = service.users().messages().list(userId="me", q=query)
    while request is not None:
        response = request.execute()
        ids.extend(m["id"] for m in response.get("messages", []))
        request = service.users().messages().list_next(request, response)
    return ids


def get_metadata(service, message_id: str) -> Dict[str, Optional[str]]:
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata", metadataHeaders=_METADATA_HEADERS)
        .execute()
    )
    headers = {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}
    return {name: headers.get(name) for name in _METADATA_HEADERS}


def get_full(service, message_id: str) -> dict:
    return service.users().messages().get(userId="me", id=message_id, format="full").execute()


def get_attachment_bytes(service, message_id: str, attachment_id: str) -> bytes:
    from app.sources.mime import decode_base64url

    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return decode_base64url(attachment["data"])


def history_list(service, start_history_id: str) -> Tuple[List[str], str]:
    """Returns (added_message_ids, new_history_id). Raises HttpError(404) if the
    starting historyId has expired — callers must fall back to a bounded rescan.
    """
    message_ids: List[str] = []
    new_history_id = start_history_id
    request = service.users().history().list(
        userId="me", startHistoryId=start_history_id, historyTypes=["messageAdded"]
    )
    while request is not None:
        response = request.execute()
        for record in response.get("history", []):
            for added in record.get("messagesAdded", []):
                message_ids.append(added["message"]["id"])
        if "historyId" in response:
            new_history_id = response["historyId"]
        request = service.users().history().list_next(request, response)

    seen = set()
    deduped = []
    for mid in message_ids:
        if mid not in seen:
            seen.add(mid)
            deduped.append(mid)
    return deduped, new_history_id


def get_latest_history_id(service) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return profile["historyId"]


__all__ = [
    "HttpError",
    "get_service_for_user",
    "list_message_ids",
    "get_metadata",
    "get_full",
    "get_attachment_bytes",
    "history_list",
    "get_latest_history_id",
]
