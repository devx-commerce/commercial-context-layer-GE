"""Build the canonical HTML evidence document for one approved Slack message
(build spec sections 11 and 12) and its stable message document ID.
"""

import hashlib
from dataclasses import dataclass
from html import escape
from typing import Optional


@dataclass
class SlackDocument:
    document_id: str
    title: str
    html: str


def compute_document_id(workspace_id: str, channel_id: str, message_ts: str) -> str:
    key = f"slack:{workspace_id}:{channel_id}:{message_ts}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build(
    *,
    workspace_id: str,
    channel_id: str,
    channel_name: str,
    message_ts: str,
    author_name: str,
    sent_at: str,
    thread_ts: Optional[str],
    resolved_text: str,
) -> SlackDocument:
    document_id = compute_document_id(workspace_id, channel_id, message_ts)
    # Section 14 wants "Slack channel plus timestamp" for uniqueness in the indexed
    # title; the <h1> stays just the channel name, matching the section 12 example.
    title = f"Slack: #{channel_name} @ {sent_at}"

    thread_row = ""
    if thread_ts and thread_ts != message_ts:
        thread_row = f"<dt>Thread</dt><dd>reply to {escape(thread_ts)}</dd>"

    html = (
        "<html><body>"
        f"<h1>Slack: #{escape(channel_name)}</h1>"
        "<dl>"
        f"<dt>Author</dt><dd>{escape(author_name)}</dd>"
        f"<dt>Sent</dt><dd>{escape(sent_at)}</dd>"
        f"{thread_row}"
        "</dl>"
        f"<article>{escape(resolved_text)}</article>"
        "</body></html>"
    )
    return SlackDocument(document_id=document_id, title=title, html=html)
