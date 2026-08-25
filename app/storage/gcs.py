"""Thin GCS helpers over the one private bucket.

Every write that can race (config, users.json, gmail cursor state) goes through
``write_json`` with ``if_generation_match`` set by the caller. Approved-content
writes set content type (and, for attachments, content-disposition so the original
filename survives without a metadata sidecar) and nothing else — no custom object
metadata, per the strict storage contract in build spec section 6.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from app.models import PendingOperation
from app.settings import settings

PENDING_PREFIX = "pending/operations/"

_client: Optional[storage.Client] = None


def _bucket() -> storage.Bucket:
    global _client
    if _client is None:
        _client = storage.Client(project=settings.project_id)
    return _client.bucket(settings.gcs_bucket)


@dataclass
class JsonObject:
    data: dict
    generation: int


def content_uri(path: str) -> str:
    return f"gs://{settings.gcs_bucket}/{path}"


def gs_uri_to_path(uri: str) -> str:
    prefix = f"gs://{settings.gcs_bucket}/"
    if not uri.startswith(prefix):
        raise ValueError(f"{uri!r} is not a gs:// URI in this bucket")
    return uri[len(prefix):]


def read_json(path: str) -> Optional[JsonObject]:
    blob = _bucket().blob(path)
    try:
        raw = blob.download_as_bytes()
    except NotFound:
        return None
    blob.reload()
    return JsonObject(data=json.loads(raw), generation=blob.generation)


def write_json(path: str, data: dict, if_generation_match: Optional[int] = None) -> int:
    """Write JSON. Pass if_generation_match=0 to require the object not already exist.

    Raises google.api_core.exceptions.PreconditionFailed on a lost race; callers
    should reload and retry rather than silently overwrite.
    """
    blob = _bucket().blob(path)
    blob.upload_from_string(
        json.dumps(data),
        content_type="application/json",
        if_generation_match=if_generation_match,
    )
    return blob.generation


def write_bytes(
    path: str,
    data: bytes,
    content_type: str,
    content_disposition: Optional[str] = None,
) -> None:
    blob = _bucket().blob(path)
    if content_disposition:
        blob.content_disposition = content_disposition
    blob.upload_from_string(data, content_type=content_type)


def read_bytes(path: str) -> Optional[bytes]:
    blob = _bucket().blob(path)
    try:
        return blob.download_as_bytes()
    except NotFound:
        return None


def read_text_head(path: str, max_bytes: int = 4096) -> Optional[str]:
    """Read the first max_bytes of an object, decoded as UTF-8 (best-effort).

    Used to recover an evidence document's <h1> title without loading the whole body.
    """
    blob = _bucket().blob(path)
    try:
        chunk = blob.download_as_bytes(start=0, end=max_bytes)
    except NotFound:
        return None
    return chunk.decode("utf-8", errors="ignore")


def get_content_disposition(path: str) -> Optional[str]:
    blob = _bucket().blob(path)
    try:
        blob.reload()
    except NotFound:
        return None
    return blob.content_disposition


def exists(path: str) -> bool:
    return _bucket().blob(path).exists()


def delete(path: str) -> None:
    try:
        _bucket().blob(path).delete()
    except NotFound:
        pass


def list_prefix(prefix: str) -> Iterable[str]:
    for blob in _bucket().list_blobs(prefix=prefix):
        yield blob.name


def write_pending_operation(op: PendingOperation) -> str:
    operation_id = uuid.uuid4().hex
    write_json(f"{PENDING_PREFIX}{operation_id}.json", op.model_dump(exclude_none=True))
    return operation_id


def read_pending_operation(operation_id: str) -> Optional[PendingOperation]:
    obj = read_json(f"{PENDING_PREFIX}{operation_id}.json")
    return PendingOperation.model_validate(obj.data) if obj else None


def delete_pending_operation(operation_id: str) -> None:
    delete(f"{PENDING_PREFIX}{operation_id}.json")


def list_pending_operation_ids() -> Iterable[str]:
    for name in list_prefix(PENDING_PREFIX):
        if name.endswith(".json"):
            yield name[len(PENDING_PREFIX) : -len(".json")]


__all__ = [
    "PreconditionFailed",
    "JsonObject",
    "content_uri",
    "read_json",
    "write_json",
    "write_bytes",
    "read_bytes",
    "read_text_head",
    "get_content_disposition",
    "exists",
    "delete",
    "list_prefix",
    "write_pending_operation",
    "read_pending_operation",
    "delete_pending_operation",
    "list_pending_operation_ids",
]
