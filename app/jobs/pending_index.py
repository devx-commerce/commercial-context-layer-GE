"""POST /internal/process-pending — the sole caller of app.indexing.gemini.

Every producer (Gmail/Slack ingestion) only ever writes evidence to GCS plus a
pending operation pointer; this job is where every actual Gemini upsert/delete
happens. Concentrating it here means there is exactly one retry path: leave the
pointer in place on failure and let the next 5-minute run (Cloud Scheduler) try
again. There's no per-op attempt counter — the strict pending/operations schema
(build spec section 6) has no room for one — so this relies on the Google client
libraries' own request-level exponential backoff for transient errors, plus the
fixed 5-minute scheduler cadence as the cross-run retry loop. That's a deliberate
POC simplification instead of hand-rolling stateful backoff tracking.
"""

import hashlib
import logging
from typing import Optional, Tuple

from bs4 import BeautifulSoup

from app.config_loader import ConfigError, load_config_and_users
from app.indexing import gemini
from app.models import PendingOperation
from app.policy import acl
from app.sources import mime, slack_client
from app.storage import gcs

logger = logging.getLogger(__name__)


def _path_info(path: str) -> Tuple[str, bool]:
    """Returns (account_domain, is_attachment) from an approved/ path."""
    segments = path.split("/")
    account_domain = segments[1]
    is_attachment = "attachments" in segments
    return account_domain, is_attachment


def _recover_title(path: str) -> str:
    if path.endswith("message.html"):
        head = gcs.read_text_head(path) or ""
        soup = BeautifulSoup(head, "lxml")
        h1 = soup.find("h1")
        if h1 is not None:
            return h1.get_text()
        return "Untitled"

    disposition = gcs.get_content_disposition(path)
    if disposition and "filename=" in disposition:
        return disposition.split("filename=", 1)[1].strip('"; ')
    return path.rsplit("/", 1)[-1]


def _mime_type_for_path(path: str) -> str:
    if path.endswith("message.html"):
        return "text/html"
    ext = path.rsplit(".", 1)[-1]
    return mime.mime_for_extension(ext) or "application/octet-stream"


def _handle_upsert(op: PendingOperation) -> None:
    config, users, _ = load_config_and_users()
    path = gcs.gs_uri_to_path(op.content_uri)
    account_domain, _ = _path_info(path)
    account = config.accounts.get(account_domain)
    if account is None:
        logger.warning("pending_upsert_unknown_account_domain")
        return

    readers = sorted(acl.readers_for_account(account, config.teams, users))
    title = _recover_title(path)
    mime_type = _mime_type_for_path(path)
    gemini.upsert(op.document_id, op.content_uri, mime_type, title, readers)


def _handle_delete(op: PendingOperation) -> None:
    gemini.delete(op.document_id)
    if op.content_uri:
        gcs.delete(gcs.gs_uri_to_path(op.content_uri))


def _handle_fetch_slack_attachment(op: PendingOperation) -> None:
    config, users, _ = load_config_and_users()
    channel = config.slack_channels.get(op.slack_channel_id or "")
    if channel is None:
        logger.warning("pending_fetch_attachment_unknown_channel")
        return

    data, filename, mime_type = slack_client.download_file(op.slack_file_id)
    ext = mime.extension_for_mime(mime_type)
    if ext is None:
        logger.info("slack_attachment_rejected_unsupported_type=1")
        return
    if len(data) > config.attachment_max_bytes:
        logger.info("slack_attachment_rejected_oversized=1")
        return

    normalized_filename = filename.strip()
    attachment_document_id = hashlib.sha256(
        f"{op.parent_document_id}:{hashlib.sha256(data).hexdigest()}:{normalized_filename}".encode("utf-8")
    ).hexdigest()
    path = (
        f"approved/{channel.account_domain}/slack/{op.parent_document_id}/attachments/"
        f"{attachment_document_id}.{ext}"
    )
    gcs.write_bytes(
        path, data, content_type=mime_type, content_disposition=f'attachment; filename="{normalized_filename}"'
    )

    account = config.accounts[channel.account_domain]
    readers = sorted(acl.readers_for_account(account, config.teams, users))
    gemini.upsert(attachment_document_id, gcs.content_uri(path), mime_type, normalized_filename, readers)


def process_all_pending() -> None:
    try:
        load_config_and_users()
    except ConfigError:
        logger.exception("process_pending_aborted_invalid_config")
        return

    for operation_id in list(gcs.list_pending_operation_ids()):
        op: Optional[PendingOperation] = gcs.read_pending_operation(operation_id)
        if op is None:
            continue
        try:
            if op.operation == "upsert":
                _handle_upsert(op)
            elif op.operation == "delete":
                _handle_delete(op)
            elif op.operation == "fetch_slack_attachment":
                _handle_fetch_slack_attachment(op)
            gcs.delete_pending_operation(operation_id)
        except Exception:
            logger.exception("pending_operation_failed_will_retry")
