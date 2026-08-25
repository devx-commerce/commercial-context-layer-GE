"""Slack Web API wrapper for the single central bot installation.

users.info results are cached in an in-process dict with a TTL — allowed by
build spec section 11 ("An in-memory TTL cache is allowed, but Slack user
profiles must not be persisted in GCS"). Nothing here writes to GCS.
"""

import re
import time
from typing import Dict, Optional, Tuple

import httpx
from slack_sdk import WebClient

from app.settings import require, settings
from app.storage import secret_manager

_USER_CACHE_TTL_SECONDS = 15 * 60
_user_cache: Dict[str, Tuple[str, float]] = {}
_client: Optional[WebClient] = None
_signing_secret: Optional[str] = None

_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")


def _bot_token() -> str:
    secret_name = require(settings.slack_bot_token_secret, "SLACK_BOT_TOKEN_SECRET")
    return secret_manager.access_latest(secret_name)


def get_client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=_bot_token())
    return _client


def signing_secret() -> str:
    global _signing_secret
    if _signing_secret is None:
        secret_name = require(settings.slack_signing_secret_secret, "SLACK_SIGNING_SECRET_SECRET")
        _signing_secret = secret_manager.access_latest(secret_name)
    return _signing_secret


def resolve_user_name(user_id: str) -> str:
    cached = _user_cache.get(user_id)
    now = time.monotonic()
    if cached is not None and cached[1] > now:
        return cached[0]

    try:
        response = get_client().users_info(user=user_id)
        profile = response["user"].get("profile", {})
        name = profile.get("real_name") or response["user"].get("real_name") or user_id
    except Exception:
        name = user_id

    _user_cache[user_id] = (name, now + _USER_CACHE_TTL_SECONDS)
    return name


def resolve_mentions(text: str) -> str:
    return _MENTION_RE.sub(lambda m: f"@{resolve_user_name(m.group(1))}", text)


def join_channel(channel_id: str) -> dict:
    return get_client().conversations_join(channel=channel_id)


def download_file(file_id: str) -> Tuple[bytes, str, str]:
    """Returns (bytes, filename, mime_type)."""
    info = get_client().files_info(file=file_id)
    file_obj = info["file"]
    url = file_obj["url_private_download"]
    response = httpx.get(url, headers={"Authorization": f"Bearer {_bot_token()}"}, timeout=30.0)
    response.raise_for_status()
    return response.content, file_obj.get("name", file_id), file_obj.get("mimetype", "application/octet-stream")
