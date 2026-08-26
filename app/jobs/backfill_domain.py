"""POST /internal/backfill-domain?domain=<domain> — full content re-push for a domain.

Companion to reindex_domain.py: that job patches only acl_info on documents that
are already indexed. This one re-runs a full upsert (content + title + acl_info)
for every document under approved/<domain>/**, for use after pointing
DISCOVERYENGINE_DATA_STORE_ID at a freshly created, empty data store — the
source files already sit in GCS, so nothing needs to be re-collected from
Gmail/Slack, just re-pushed to Gemini Enterprise.
"""

from app.config_loader import load_config_and_users
from app.indexing import gemini
from app.jobs.pending_index import _mime_type_for_path, _recover_title
from app.policy import acl
from app.storage import gcs


def run(domain: str) -> dict:
    config, users, _ = load_config_and_users()
    account = config.accounts.get(domain)
    if account is None:
        raise ValueError(f"unknown account domain: {domain}")

    readers = sorted(acl.readers_for_account(account, config.teams, users))

    paths_by_document_id = {}
    for path in gcs.list_prefix(f"approved/{domain}/"):
        if path.endswith("message.html"):
            paths_by_document_id[path.split("/")[3]] = path
        elif "/attachments/" in path:
            filename = path.rsplit("/", 1)[-1]
            paths_by_document_id[filename.rsplit(".", 1)[0]] = path

    for document_id, path in paths_by_document_id.items():
        title = _recover_title(path)
        mime_type = _mime_type_for_path(path)
        gemini.upsert(document_id, gcs.content_uri(path), mime_type, title, readers)

    return {"domain": domain, "documents_backfilled": len(paths_by_document_id)}
