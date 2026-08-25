"""Gmail MIME helpers: base64url decoding, body-part selection, attachment listing,
and HTML sanitization shared by email/Slack normalization.
"""

import base64
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

_STRIP_TAGS = ("script", "style", "form", "iframe", "object", "embed", "link", "meta")

# POC-supported attachment types (build spec section 13). Anything else is out of
# scope; encrypted/corrupt files aren't specially detected — they just fail to
# process downstream and fall into the generic error-counter path (section 18).
SUPPORTED_ATTACHMENT_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def extension_for_mime(mime_type: str) -> Optional[str]:
    return SUPPORTED_ATTACHMENT_MIME_TYPES.get(mime_type)


_EXTENSION_TO_MIME = {ext: mime_type for mime_type, ext in SUPPORTED_ATTACHMENT_MIME_TYPES.items()}


def mime_for_extension(ext: str) -> Optional[str]:
    return _EXTENSION_TO_MIME.get(ext)


def decode_base64url(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _walk_parts(part)


def find_body(payload: dict) -> Optional[Dict[str, str]]:
    """Prefer text/plain; fall back to text/html. Returns {"mime_type", "text"}."""
    html_fallback = None
    for part in _walk_parts(payload):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if not data or body.get("attachmentId"):
            continue
        if mime_type == "text/plain":
            return {"mime_type": "text/plain", "text": decode_base64url(data).decode("utf-8", errors="replace")}
        if mime_type == "text/html" and html_fallback is None:
            html_fallback = decode_base64url(data).decode("utf-8", errors="replace")
    if html_fallback is not None:
        return {"mime_type": "text/html", "text": html_fallback}
    return None


def list_attachment_parts(payload: dict) -> List[Dict[str, object]]:
    """Parts with a filename and an attachmentId — candidate attachments."""
    attachments = []
    for part in _walk_parts(payload):
        filename = part.get("filename")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if filename and attachment_id:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": part.get("mimeType", "application/octet-stream"),
                    "attachment_id": attachment_id,
                    "size": body.get("size", 0),
                }
            )
    return attachments


def sanitize_html(html: str) -> str:
    """Strip scripts, styles, forms, and remote-resource-loading tags/attributes.
    Does not fetch remote images — it removes them instead of rendering.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for img in soup.find_all("img"):
        img.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on") or attr in ("srcset", "background"):
                del tag[attr]
            if attr == "src" and tag.name != "img":
                del tag[attr]
    body = soup.body or soup
    return body.decode() if hasattr(body, "decode") else str(body)


def plain_text_to_html(text: str) -> str:
    from html import escape

    return f"<pre>{escape(text)}</pre>"
