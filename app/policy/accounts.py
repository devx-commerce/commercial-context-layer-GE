"""Approval policy — build spec sections 10 and 11.

Gmail: exact-domain match against From/To/Cc/Bcc, using an RFC-aware parser
(stdlib email.utils). 0 matches discards; exactly 1 approves; >1 discards as
ambiguous. No substring/subdomain matching, and internal domains are never
looked up as account domains because they are matched against `account_domains`
only, which never includes internal_domains.

Slack: a channel is approved only when its immutable channel ID is a key in the
configured whitelist.
"""

from email.utils import getaddresses
from typing import Dict, Iterable, Optional

from app.models import SlackChannelConfig


def normalize_domain(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def _domains_in_header(header_value: Optional[str]) -> set:
    if not header_value:
        return set()
    domains = set()
    for _, address in getaddresses([header_value]):
        if "@" in address:
            domains.add(normalize_domain(address.rsplit("@", 1)[1]))
    return domains


def match_gmail_account(
    headers: Dict[str, Optional[str]],
    account_domains: Iterable[str],
) -> Optional[str]:
    """headers: dict with optional 'From'/'To'/'Cc'/'Bcc' string values.

    Returns the single matched account domain, or None if the message should
    be discarded (no match, or more than one match).
    """
    configured = {normalize_domain(d) for d in account_domains}
    found = set()
    for field in ("From", "To", "Cc", "Bcc"):
        found |= _domains_in_header(headers.get(field))

    matched = found & configured
    if len(matched) == 1:
        return next(iter(matched))
    return None


def match_slack_channel(
    channel_id: str,
    slack_channels: Dict[str, SlackChannelConfig],
) -> Optional[SlackChannelConfig]:
    return slack_channels.get(channel_id)
