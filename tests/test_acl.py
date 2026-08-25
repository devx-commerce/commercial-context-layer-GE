from app.models import AccountConfig, TeamConfig, UserRecord
from app.policy.acl import readers_for_account, team_ancestors

TEAMS = {
    "commercial": TeamConfig(parent=None),
    "enterprise": TeamConfig(parent="commercial"),
    "enterprise-north": TeamConfig(parent="enterprise"),
    "enterprise-south": TeamConfig(parent="enterprise"),
    "base": TeamConfig(parent="commercial"),
}

USERS = {
    "north@devx.com": UserRecord(teams=["enterprise-north"]),
    "south@devx.com": UserRecord(teams=["enterprise-south"]),
    "enterprise-lead@devx.com": UserRecord(teams=["enterprise"]),
    "commercial-lead@devx.com": UserRecord(teams=["commercial"]),
    "new-user@devx.com": UserRecord(teams=["base"]),
    "specialist@devx.com": UserRecord(teams=["base"]),
    "contractor@devx.com": UserRecord(teams=["base"]),
}


def test_team_ancestors():
    assert team_ancestors("enterprise-north", TEAMS) == ["enterprise", "commercial"]
    assert team_ancestors("commercial", TEAMS) == []


def test_parent_and_ancestors_see_descendant_account():
    account = AccountConfig(name="HT", teams=["enterprise-north"])
    readers = readers_for_account(account, TEAMS, USERS)
    assert "north@devx.com" in readers
    assert "enterprise-lead@devx.com" in readers
    assert "commercial-lead@devx.com" in readers


def test_sibling_team_is_isolated():
    account = AccountConfig(name="HT", teams=["enterprise-north"])
    readers = readers_for_account(account, TEAMS, USERS)
    assert "south@devx.com" not in readers


def test_base_is_isolated_from_other_branches():
    account = AccountConfig(name="HT", teams=["enterprise-north"])
    readers = readers_for_account(account, TEAMS, USERS)
    assert "new-user@devx.com" not in readers


def test_allow_users_grants_explicit_access():
    account = AccountConfig(name="HT", teams=["enterprise-north"], allow_users=["specialist@devx.com"])
    readers = readers_for_account(account, TEAMS, USERS)
    assert "specialist@devx.com" in readers


def test_deny_always_wins_even_over_team_membership():
    account = AccountConfig(name="HT", teams=["enterprise-north"], deny_users=["north@devx.com"])
    readers = readers_for_account(account, TEAMS, USERS)
    assert "north@devx.com" not in readers


def test_deny_wins_over_allow():
    account = AccountConfig(
        name="HT",
        teams=["enterprise-north"],
        allow_users=["contractor@devx.com"],
        deny_users=["contractor@devx.com"],
    )
    readers = readers_for_account(account, TEAMS, USERS)
    assert "contractor@devx.com" not in readers
