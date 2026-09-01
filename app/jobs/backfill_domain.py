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
from app.jobs.pending_index import (
    _merge_owner,
    _mime_type_for_path,
    _recover_title,
    collect_document_paths,
)
from app.policy import acl
from app.storage import gcs


def run(domain: str) -> dict:
    config, _, _ = load_config_and_users()
    if domain not in config.accounts:
        raise ValueError(f"unknown account domain: {domain}")

    backfilled = 0

    for channel_id, channel in config.slack_channels.items():
        if channel.account_domain != domain:
            continue
        readers = sorted(acl.slack_readers(channel_id, domain, config))
        for document_id, path in collect_document_paths(f"approved/{domain}/slack/{channel_id}/").items():
            gemini.upsert(document_id, gcs.content_uri(path), _mime_type_for_path(path), _recover_title(path), readers)
            backfilled += 1

    for document_id, path in collect_document_paths(f"approved/{domain}/gmail/").items():
        owners = _merge_owner(document_id, None)
        readers = sorted(acl.gmail_readers(owners, domain, config))
        gemini.upsert(document_id, gcs.content_uri(path), _mime_type_for_path(path), _recover_title(path), readers)
        backfilled += 1

    return {"domain": domain, "documents_backfilled": backfilled}
