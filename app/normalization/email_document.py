"""Build the canonical HTML evidence document for one approved Gmail message
(build spec sections 10 and 12) and its stable, cross-mailbox document ID.
"""

import hashlib
from dataclasses import dataclass
from html import escape
from typing import Optional

from app.sources.mime import sanitize_html


@dataclass
class EmailDocument:
    document_id: str
    title: str
    html: str


def _normalize_message_id(raw: str) -> str:
    return raw.strip().strip("<>").strip()


def compute_document_id(
    message_id: Optional[str],
    sender: str,
    recipients: str,
    date: str,
    subject: str,
    body_text: str,
) -> str:
    if message_id:
        key = "gmail:" + _normalize_message_id(message_id)
    else:
        key = "gmail:" + "|".join(
            [sender.strip().lower(), recipients.strip().lower(), date.strip(), subject.strip(), body_text]
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build(
    *,
    message_id: Optional[str],
    sender: str,
    to: str,
    cc: str,
    subject: str,
    sent_at: str,
    body_mime_type: str,
    body_text: str,
) -> EmailDocument:
    document_id = compute_document_id(message_id, sender, to, sent_at, subject, body_text)
    title = f"Email: {subject}" if subject else "Email"

    if body_mime_type == "text/html":
        article = sanitize_html(body_text)
    else:
        article = f"<pre>{escape(body_text)}</pre>"

    html = (
        "<html><body>"
        f"<h1>{escape(title)}</h1>"
        "<dl>"
        f"<dt>From</dt><dd>{escape(sender)}</dd>"
        f"<dt>To</dt><dd>{escape(to)}</dd>"
        f"<dt>Cc</dt><dd>{escape(cc)}</dd>"
        f"<dt>Sent</dt><dd>{escape(sent_at)}</dd>"
        "</dl>"
        f"<article>{article}</article>"
        "</body></html>"
    )
    return EmailDocument(document_id=document_id, title=title, html=html)
