"""POST /internal/reindex-domain?domain=<domain> — build spec section 8.

Recomputes readers for every document under approved/<domain>/** and patches
just the ACL field on each (no title needed — see the plan's note on why a
partial acl_info-only patch sidesteps the "no persisted title" constraint).
Document IDs are recovered from the GCS path itself: no sidecar list is needed
because the layout embeds the document ID in the path (section 6). This is a
rare, admin-triggered action, so it runs synchronously rather than going
through the pending queue.
"""

from app.config_loader import load_config_and_users
from app.indexing import gemini
from app.policy import acl
from app.storage import gcs


def run(domain: str) -> dict:
    config, users, _ = load_config_and_users()
    account = config.accounts.get(domain)
    if account is None:
        raise ValueError(f"unknown account domain: {domain}")

    readers = sorted(acl.readers_for_account(account, config.teams, users))

    document_ids = set()
    for path in gcs.list_prefix(f"approved/{domain}/"):
        if path.endswith("message.html"):
            document_ids.add(path.split("/")[3])
        elif "/attachments/" in path:
            filename = path.rsplit("/", 1)[-1]
            document_ids.add(filename.rsplit(".", 1)[0])

    for document_id in document_ids:
        gemini.patch_acl(document_id, readers)

    return {"domain": domain, "documents_patched": len(document_ids)}
