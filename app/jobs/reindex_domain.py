"""POST /internal/reindex-domain?domain=<domain> — ACL-only reconcile.

Recomputes readers for every document under approved/<domain>/** and patches
just the ACL field on each. Slack documents get live channel membership +
superusers (per channel — the channel ID is embedded in the evidence path);
Gmail documents get their accumulated owners + superusers. This is the manual
safety net behind the event-driven resync (member_joined/left_channel), e.g.
after editing the superusers list.
"""

from app.config_loader import load_config_and_users
from app.indexing import gemini
from app.jobs.pending_index import _merge_owner, collect_document_paths
from app.policy import acl


def run(domain: str) -> dict:
    config, _, _ = load_config_and_users()
    if domain not in config.accounts:
        raise ValueError(f"unknown account domain: {domain}")

    patched = 0

    for channel_id, channel in config.slack_channels.items():
        if channel.account_domain != domain:
            continue
        readers = sorted(acl.slack_readers(channel_id, config))
        for document_id in collect_document_paths(f"approved/{domain}/slack/{channel_id}/"):
            gemini.patch_acl(document_id, readers)
            patched += 1

    for document_id in collect_document_paths(f"approved/{domain}/gmail/"):
        owners = _merge_owner(document_id, None)
        readers = sorted(acl.gmail_readers(owners, config))
        gemini.patch_acl(document_id, readers)
        patched += 1

    return {"domain": domain, "documents_patched": patched}
