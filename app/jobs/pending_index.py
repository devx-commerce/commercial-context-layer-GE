"""POST /internal/process-pending — the sole caller of app.indexing.gemini.

Every producer (Gmail/Slack ingestion) only ever writes evidence to GCS plus a
pending operation pointer; this job is where every actual Gemini upsert/delete
happens. Concentrating it here means there is exactly one retry path: leave the
pointer in place on failure and let the next 5-minute run (Cloud Scheduler) try
again.

Readers are derived here, at index time:
  - Slack documents (approved/<domain>/slack/<channel>/...): live channel
    membership + superusers.
  - Gmail documents (approved/<domain>/gmail/...): the union of onboarded
    mailboxes that ingested this document (state/owners/<doc>.json) + superusers.
"""

import hashlib
import logging
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from app.config_loader import ConfigError, load_config_and_users
from app.indexing import gemini
from app.models import Config, PendingOperation
from app.policy import acl
from app.sources import mime, slack_client
from app.storage import gcs

logger = logging.getLogger(__name__)

_OWNERS_PREFIX = "state/owners/"


def _owners_path(document_id: str) -> str:
    return f"{_OWNERS_PREFIX}{document_id}.json"


def _merge_owner(document_id: str, owner_email: Optional[str], max_retries: int = 5) -> List[str]:
    """Add owner_email to the document's accumulated owner set (generation-safe)
    and return the full set. A document can be owned by several mailboxes when
    more than one onboarded user has the same email in their inbox."""
    for _ in range(max_retries):
        obj = gcs.read_json(_owners_path(document_id))
        owners = set(obj.data.get("owners", [])) if obj is not None else set()
        generation = obj.generation if obj is not None else 0

        if owner_email is None or owner_email in owners:
            return sorted(owners)

        owners.add(owner_email)
        try:
            gcs.write_json(_owners_path(document_id), {"owners": sorted(owners)}, if_generation_match=generation)
            return sorted(owners)
        except gcs.PreconditionFailed:
            continue
    raise RuntimeError(f"failed to merge owner for document {document_id} (concurrent update)")


def _split_approved_path(path: str) -> Tuple[str, str, List[str]]:
    """Returns (account_domain, source, remaining_segments) for an approved/ path."""
    segments = path.split("/")
    return segments[1], segments[2], segments[3:]


def _readers_for_path(path: str, config: Config, owner_email: Optional[str], document_id: str) -> List[str]:
    _, source, rest = _split_approved_path(path)
    if source == "slack":
        channel_id = rest[0]
        return sorted(acl.slack_readers(channel_id, config))
    owners = _merge_owner(document_id, owner_email)
    return sorted(acl.gmail_readers(owners, config))


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
    config, _, _ = load_config_and_users()
    path = gcs.gs_uri_to_path(op.content_uri)
    account_domain, _, _ = _split_approved_path(path)
    if account_domain not in config.accounts:
        logger.warning("pending_upsert_unknown_account_domain")
        return

    readers = _readers_for_path(path, config, op.owner_email, op.document_id)
    title = _recover_title(path)
    mime_type = _mime_type_for_path(path)
    gemini.upsert(op.document_id, op.content_uri, mime_type, title, readers)


def _handle_delete(op: PendingOperation) -> None:
    gemini.delete(op.document_id)
    if op.content_uri:
        gcs.delete(gcs.gs_uri_to_path(op.content_uri))
        gcs.delete(_owners_path(op.document_id))


def _handle_fetch_slack_attachment(op: PendingOperation) -> None:
    config, _, _ = load_config_and_users()
    channel_id = op.slack_channel_id or ""
    channel = config.slack_channels.get(channel_id)
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
        f"approved/{channel.account_domain}/slack/{channel_id}/{op.parent_document_id}/attachments/"
        f"{attachment_document_id}.{ext}"
    )
    gcs.write_bytes(
        path, data, content_type=mime_type, content_disposition=f'attachment; filename="{normalized_filename}"'
    )

    readers = sorted(acl.slack_readers(channel_id, config))
    gemini.upsert(attachment_document_id, gcs.content_uri(path), mime_type, normalized_filename, readers)


def collect_document_paths(prefix: str) -> dict:
    """{document_id: evidence_path} for everything under an approved/ prefix.
    Message documents live at .../<doc_id>/message.html; attachment documents
    are named by their own ID at .../attachments/<doc_id>.<ext>."""
    paths_by_document_id = {}
    for path in gcs.list_prefix(prefix):
        if path.endswith("message.html"):
            paths_by_document_id[path.split("/")[-2]] = path
        elif "/attachments/" in path:
            filename = path.rsplit("/", 1)[-1]
            paths_by_document_id[filename.rsplit(".", 1)[0]] = path
    return paths_by_document_id


def _handle_resync_channel_acl(op: PendingOperation) -> None:
    config, _, _ = load_config_and_users()
    channel_id = op.slack_channel_id or ""
    channel = config.slack_channels.get(channel_id)
    if channel is None:
        logger.warning("pending_resync_unknown_channel")
        return

    readers = sorted(acl.slack_readers(channel_id, config))
    document_ids = collect_document_paths(f"approved/{channel.account_domain}/slack/{channel_id}/")
    for document_id in document_ids:
        gemini.patch_acl(document_id, readers)
    logger.info("channel_acl_resynced documents=%d", len(document_ids))


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
            elif op.operation == "resync_channel_acl":
                _handle_resync_channel_acl(op)
            gcs.delete_pending_operation(operation_id)
        except Exception:
            logger.exception("pending_operation_failed_will_retry")
