"""ACL algorithm (v2) — channel-membership based, with a superuser override.

    slack readers  = (live channel members whose email is in internal_domains)
                     UNION superusers
    gmail readers  = (onboarded mailboxes the document was ingested from)
                     UNION superusers

Slack membership is read live from the Slack API at index/patch time, never
persisted. Superusers (config.superusers) can read every document regardless
of channel membership or mailbox ownership.
"""

from typing import Iterable, Set

from app.models import Config
from app.sources import slack_client


def _internal_only(emails: Iterable[str], config: Config) -> Set[str]:
    internal = {d.lower() for d in config.internal_domains}
    result = set()
    for email in emails:
        normalized = email.strip().lower()
        if "@" in normalized and normalized.split("@", 1)[1] in internal:
            result.add(normalized)
    return result


def superusers(config: Config) -> Set[str]:
    return {email.strip().lower() for email in config.superusers}


def slack_readers(channel_id: str, config: Config) -> Set[str]:
    members = slack_client.channel_member_emails(channel_id)
    return _internal_only(members, config) | superusers(config)


def gmail_readers(owners: Iterable[str], config: Config) -> Set[str]:
    return {o.strip().lower() for o in owners} | superusers(config)
