"""Gmail initial + incremental scan orchestration (build spec section 10).

Ingestion only ever (1) writes approved evidence bytes to GCS and (2) writes one
pending "upsert" operation per document. It never calls Gemini directly — the
5-minute process-pending job (app.jobs.pending_index) is the only caller of
app.indexing.gemini, so there is exactly one retry path instead of two.
"""

import hashlib
import logging
from typing import Dict

from app.models import Config, GmailState, PendingOperation, UserRecord
from app.policy import accounts
from app.normalization import email_document
from app.sources import gmail_client, mime
from app.storage import gcs

logger = logging.getLogger(__name__)

_METADATA_FIELDS = ("From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID")


def _state_path(email: str) -> str:
    from urllib.parse import quote

    return f"state/gmail/{quote(email, safe='')}.json"


def load_state(email: str) -> GmailState:
    obj = gcs.read_json(_state_path(email))
    if obj is None:
        return GmailState(status="active", history_id=None)
    return GmailState.model_validate(obj.data)


def save_state(email: str, state: GmailState) -> None:
    gcs.write_json(_state_path(email), state.model_dump(exclude_none=True))


def _write_evidence_and_queue(
    account_domain: str, document: email_document.EmailDocument
) -> None:
    path = f"approved/{account_domain}/gmail/{document.document_id}/message.html"
    gcs.write_bytes(path, document.html.encode("utf-8"), content_type="text/html")
    gcs.write_pending_operation(
        PendingOperation(operation="upsert", document_id=document.document_id, content_uri=gcs.content_uri(path))
    )


def _process_attachments(service, message_id: str, account_domain: str, parent_document_id: str, max_bytes: int) -> None:
    full = gmail_client.get_full(service, message_id)
    for part in mime.list_attachment_parts(full.get("payload", {})):
        ext = mime.extension_for_mime(part["mime_type"])
        if ext is None:
            continue
        try:
            data = gmail_client.get_attachment_bytes(service, message_id, part["attachment_id"])
        except Exception:
            logger.warning("gmail_attachment_fetch_failed")
            continue
        if len(data) > max_bytes:
            logger.info("gmail_attachment_rejected_oversized=1")
            continue

        normalized_filename = part["filename"].strip()
        attachment_document_id = hashlib.sha256(
            f"{parent_document_id}:{hashlib.sha256(data).hexdigest()}:{normalized_filename}".encode("utf-8")
        ).hexdigest()
        path = (
            f"approved/{account_domain}/gmail/{parent_document_id}/attachments/"
            f"{attachment_document_id}.{ext}"
        )
        try:
            gcs.write_bytes(
                path,
                data,
                content_type=part["mime_type"],
                content_disposition=f'attachment; filename="{normalized_filename}"',
            )
        except Exception:
            logger.warning("gmail_attachment_write_failed")
            continue
        gcs.write_pending_operation(
            PendingOperation(operation="upsert", document_id=attachment_document_id, content_uri=gcs.content_uri(path))
        )


def _approve_and_process(service, message_id: str, config: Config) -> None:
    headers = gmail_client.get_metadata(service, message_id)
    account_domain = accounts.match_gmail_account(headers, config.accounts.keys())
    if account_domain is None:
        logger.info("gmail_messages_discarded=1")
        return

    full = gmail_client.get_full(service, message_id)
    body = mime.find_body(full.get("payload", {})) or {"mime_type": "text/plain", "text": ""}

    document = email_document.build(
        message_id=headers.get("Message-ID"),
        sender=headers.get("From") or "",
        to=headers.get("To") or "",
        cc=headers.get("Cc") or "",
        subject=headers.get("Subject") or "",
        sent_at=headers.get("Date") or "",
        body_mime_type=body["mime_type"],
        body_text=body["text"],
    )
    _write_evidence_and_queue(account_domain, document)
    _process_attachments(service, message_id, account_domain, document.document_id, config.attachment_max_bytes)


def run_initial_scan(email: str, gmail_secret: str, config: Config) -> None:
    service = gmail_client.get_service_for_user(gmail_secret)
    message_ids = gmail_client.list_message_ids(service, f"newer_than:{config.poc_backfill_days}d")
    for message_id in message_ids:
        try:
            _approve_and_process(service, message_id, config)
        except Exception:
            logger.exception("gmail_message_processing_failed")
    history_id = gmail_client.get_latest_history_id(service)
    save_state(email, GmailState(status="active", history_id=history_id))


def run_incremental_scan(email: str, gmail_secret: str, config: Config) -> None:
    service = gmail_client.get_service_for_user(gmail_secret)
    state = load_state(email)
    if state.history_id is None:
        run_initial_scan(email, gmail_secret, config)
        return

    try:
        message_ids, new_history_id = gmail_client.history_list(service, state.history_id)
    except gmail_client.HttpError as exc:
        if getattr(exc, "status_code", None) == 404 or getattr(getattr(exc, "resp", None), "status", None) == 404:
            logger.info("gmail_history_id_expired_rescanning")
            run_initial_scan(email, gmail_secret, config)
            return
        raise

    for message_id in message_ids:
        try:
            _approve_and_process(service, message_id, config)
        except Exception:
            logger.exception("gmail_message_processing_failed")

    save_state(email, GmailState(status="active", history_id=new_history_id))


def run_for_all_active_users(config: Config, users: Dict[str, UserRecord]) -> None:
    for email, user in users.items():
        if not user.gmail_secret:
            continue
        state = load_state(email)
        if state.status != "active":
            continue
        try:
            run_incremental_scan(email, user.gmail_secret, config)
        except gmail_client.HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 401:
                save_state(email, GmailState(status="reauthorization_required", history_id=state.history_id))
            else:
                logger.exception("gmail_poll_failed_for_user")
        except Exception:
            logger.exception("gmail_poll_failed_for_user")
