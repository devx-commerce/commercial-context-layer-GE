"""Discovery Engine (Gemini Enterprise) document upsert / delete / ACL-only patch.

Builds each request in memory per call — nothing here is persisted to GCS. Title
travels in struct_data.title only; no other struct_data fields are ever set, per
build spec section 14 ("do not persist structData, participant lists, ... or
other searchable sidecars").

NOTE: DocumentServiceClient.update_document()'s flattened kwargs don't include
allow_missing, even though the underlying UpdateDocumentRequest message has the
field (confirmed against the installed google-cloud-discoveryengine build) - so
every update_document call here goes through an explicit request object instead
of the convenience kwargs.
"""

from typing import Iterable, List, Optional

from google.api_core.exceptions import NotFound
from google.cloud import discoveryengine_v1 as de
from google.protobuf import field_mask_pb2

from app.settings import require, settings

_client: Optional[de.DocumentServiceClient] = None


def _get_client() -> de.DocumentServiceClient:
    global _client
    if _client is None:
        _client = de.DocumentServiceClient()
    return _client


def _parent() -> str:
    data_store_id = require(settings.discoveryengine_data_store_id, "DISCOVERYENGINE_DATA_STORE_ID")
    return (
        f"projects/{settings.project_id}/locations/{settings.discoveryengine_location}"
        f"/collections/{settings.discoveryengine_collection}"
        f"/dataStores/{data_store_id}/branches/default_branch"
    )


def _document_name(document_id: str) -> str:
    return f"{_parent()}/documents/{document_id}"


def _acl_info(readers: Iterable[str]) -> de.Document.AclInfo:
    return de.Document.AclInfo(
        readers=[
            de.Document.AclInfo.AccessRestriction(
                principals=[de.Principal(user_id=email) for email in readers]
            )
        ]
    )


def upsert(document_id: str, content_uri: str, mime_type: str, title: str, readers: List[str]) -> None:
    document = de.Document(
        id=document_id,
        name=_document_name(document_id),
        content=de.Document.Content(uri=content_uri, mime_type=mime_type),
        struct_data={"title": title},
        acl_info=_acl_info(readers),
    )
    request = de.UpdateDocumentRequest(document=document, allow_missing=True)
    _get_client().update_document(request=request)


def delete(document_id: str) -> None:
    _get_client().delete_document(name=_document_name(document_id))


def patch_acl(document_id: str, readers: List[str]) -> bool:
    """Patch only acl_info. Returns False when the document isn't indexed yet
    (despite allow_missing, the server refuses a masked update on a missing
    document) — safe to skip: its evidence is still in the pending queue and
    the eventual upsert computes fresh readers anyway."""
    document = de.Document(name=_document_name(document_id), acl_info=_acl_info(readers))
    update_mask = field_mask_pb2.FieldMask(paths=["acl_info"])
    request = de.UpdateDocumentRequest(document=document, update_mask=update_mask, allow_missing=True)
    try:
        _get_client().update_document(request=request)
    except NotFound:
        return False
    return True
