"""Config validation — build spec section 7's "must fail" rules, one function per rule.

Used by scripts/validate_config.py (local config.json only), scripts/upload_config.py
(before every upload), and at service startup (fail closed per section 18). Rules
that need the user registry too (allow/deny membership, per-user secret refs) take
``users`` as an optional second argument — pass None to skip those when only
validating config.json in isolation.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

from app.models import Config, UserRecord

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_SECRET_RESOURCE_RE = re.compile(r"^projects/[^/]+/secrets/[^/]+$")


def _no_duplicate_keys_hook(pairs: List[Tuple[str, object]]) -> dict:
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"duplicate key: {key!r}")
        seen.add(key)
    return dict(pairs)


def parse_config_json(raw_text: str) -> Tuple[Optional[dict], List[str]]:
    """Parse config.json text, catching duplicate keys the plain json module would
    otherwise silently collapse (this is what catches a Slack channel declared
    twice under section 7's rule)."""
    try:
        return json.loads(raw_text, object_pairs_hook=_no_duplicate_keys_hook), []
    except ValueError as exc:
        return None, [f"invalid JSON: {exc}"]


def _is_normalized_domain(value: str) -> bool:
    return bool(_DOMAIN_RE.match(value)) and value == value.strip().lower()


def _is_normalized_email(value: str) -> bool:
    if value != value.strip().lower() or value.count("@") != 1:
        return False
    _, domain = value.split("@")
    return _is_normalized_domain(domain)


def _find_cycle(teams: Dict[str, "object"]) -> Optional[str]:
    for start in teams:
        visited = set()
        current = start
        while current is not None:
            if current in visited:
                return start
            visited.add(current)
            current = teams[current].parent if current in teams else None
    return None


def validate(config: Config, users: Optional[Dict[str, UserRecord]] = None) -> List[str]:
    errors: List[str] = []

    for domain in config.internal_domains:
        if not _is_normalized_domain(domain):
            errors.append(f"internal_domains: {domain!r} is not a normalized domain")

    for team_name, team in config.teams.items():
        if team.parent is not None and team.parent not in config.teams:
            errors.append(f"teams.{team_name}: parent {team.parent!r} does not exist")

    cycle_at = _find_cycle(config.teams)
    if cycle_at is not None:
        errors.append(f"teams: cycle detected reachable from {cycle_at!r}")
    else:
        leaves = {name for name in config.teams if name not in {t.parent for t in config.teams.values()}}
        if config.default_team not in config.teams:
            errors.append(f"default_team {config.default_team!r} does not exist")
        elif config.default_team not in leaves:
            errors.append(f"default_team {config.default_team!r} is not a leaf team")

    for domain, account in config.accounts.items():
        if not _is_normalized_domain(domain):
            errors.append(f"accounts: {domain!r} is not a normalized domain")
        for team_name in account.teams:
            if team_name not in config.teams:
                errors.append(f"accounts.{domain}: references missing team {team_name!r}")
        if users is not None:
            for email in [*account.allow_users, *account.deny_users]:
                if not _is_normalized_email(email):
                    errors.append(f"accounts.{domain}: {email!r} is not a normalized email")
                elif email not in users:
                    errors.append(f"accounts.{domain}: {email!r} is not a registered internal user")

    for channel_id, channel in config.slack_channels.items():
        if channel.account_domain not in config.accounts:
            errors.append(
                f"slack_channels.{channel_id}: references missing account domain "
                f"{channel.account_domain!r}"
            )

    if users is not None:
        for email, user in users.items():
            if not _is_normalized_email(email):
                errors.append(f"users: {email!r} is not a normalized email")
            if user.gmail_secret is not None and not _SECRET_RESOURCE_RE.match(user.gmail_secret):
                errors.append(
                    f"users.{email}: gmail_secret {user.gmail_secret!r} is not a valid "
                    "Secret Manager resource name"
                )

    return errors
