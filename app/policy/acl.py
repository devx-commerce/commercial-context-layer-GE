"""ACL algorithm — build spec section 8, implemented exactly as the formula there:

    base = UNION(users assigned to team, users assigned to every ancestor)
           for every account.teams entry
    readers = (base UNION account.allow_users) MINUS account.deny_users

Team membership is derived from state/users.json only; it is never duplicated
into team definitions. Deny always wins, even over an explicit allow.
"""

from typing import Dict, List, Set

from app.models import AccountConfig, TeamConfig, UserRecord


def team_ancestors(team: str, teams: Dict[str, TeamConfig]) -> List[str]:
    """Ancestors of `team`, nearest first. Does not include `team` itself."""
    ancestors = []
    seen = {team}
    current = teams[team].parent
    while current is not None and current not in seen:
        ancestors.append(current)
        seen.add(current)
        current = teams[current].parent if current in teams else None
    return ancestors


def is_leaf(team: str, teams: Dict[str, TeamConfig]) -> bool:
    return team not in {t.parent for t in teams.values()}


def readers_for_account(
    account: AccountConfig,
    teams: Dict[str, TeamConfig],
    users: Dict[str, UserRecord],
) -> Set[str]:
    base: Set[str] = set()
    for team in account.teams:
        eligible_teams = {team, *team_ancestors(team, teams)}
        for email, user in users.items():
            if eligible_teams & set(user.teams):
                base.add(email)

    readers = (base | set(account.allow_users)) - set(account.deny_users)
    return readers
