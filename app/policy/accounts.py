"""Approval policy — build spec sections 10 and 11.

Gmail: exact-domain match against From/To/Cc/Bcc, using an RFC-aware parser
(stdlib email.utils), plus each account's explicit allowed_senders as an
exact-address alternative to owning the whole domain. 0 matches discards;
exactly 1 matched account approves; >1 discards as ambiguous. No
substring/subdomain matching, and internal domains are never looked up as
account domains because they are matched against configured account domains
only, which never includes internal_domains.

Slack: a channel is approved only when its immutable channel ID is a key in the
configured whitelist.
"""

from email.utils import getaddresses
from typing import Dict, Optional

from app.models import AccountConfig, SlackChannelConfig


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


def _addresses_in_header(header_value: Optional[str]) -> set:
    if not header_value:
        return set()
    addresses = set()
    for _, address in getaddresses([header_value]):
        if "@" in address:
            addresses.add(address.strip().lower())
    return addresses


def match_gmail_account(
    headers: Dict[str, Optional[str]],
    accounts: Dict[str, AccountConfig],
) -> Optional[str]:
    """headers: dict with optional 'From'/'To'/'Cc'/'Bcc' string values.

    An account matches when either its domain, or one of its configured
    allowed_senders, appears among the header addresses. Returns the single
    matched account domain, or None if the message should be discarded (no
    match, or more than one account matched).
    """
    found_domains = set()
    found_addresses = set()
    for field in ("From", "To", "Cc", "Bcc"):
        found_domains |= _domains_in_header(headers.get(field))
        found_addresses |= _addresses_in_header(headers.get(field))

    matched = set()
    for domain, account in accounts.items():
        allowed_senders = {a.strip().lower() for a in account.allowed_senders}
        if normalize_domain(domain) in found_domains or allowed_senders & found_addresses:
            matched.add(domain)

    if len(matched) == 1:
        return next(iter(matched))
    return None


def match_slack_channel(
    channel_id: str,
    slack_channels: Dict[str, SlackChannelConfig],
) -> Optional[SlackChannelConfig]:
    return slack_channels.get(channel_id)
