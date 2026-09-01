from app.models import AccountConfig, Config, SlackChannelConfig
from app.policy import acl


def _config(**overrides) -> Config:
    data = dict(
        version=1,
        internal_domains=["devx.com"],
        superusers=["yash@devx.com"],
        poc_backfill_days=3,
        attachment_max_bytes=100,
        accounts={"hindustantimes.com": AccountConfig(name="HT")},
        slack_channels={
            "C1": SlackChannelConfig(name="commercial-pursuit", account_domain="hindustantimes.com")
        },
    )
    data.update(overrides)
    return Config(**data)


def _stub_members(monkeypatch, emails):
    monkeypatch.setattr(acl.slack_client, "channel_member_emails", lambda channel_id: emails)


def test_slack_readers_are_channel_members(monkeypatch):
    _stub_members(monkeypatch, ["navya@devx.com", "someone@devx.com"])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config())
    assert "navya@devx.com" in readers
    assert "someone@devx.com" in readers


def test_slack_readers_always_include_superusers(monkeypatch):
    _stub_members(monkeypatch, ["navya@devx.com"])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config())
    assert "yash@devx.com" in readers


def test_non_member_is_not_a_reader(monkeypatch):
    _stub_members(monkeypatch, ["navya@devx.com"])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config())
    assert "outsider@devx.com" not in readers


def test_external_guest_members_are_excluded(monkeypatch):
    _stub_members(monkeypatch, ["navya@devx.com", "guest@client-corp.com"])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config())
    assert "guest@client-corp.com" not in readers


def test_slack_member_emails_are_normalized(monkeypatch):
    _stub_members(monkeypatch, ["  Navya@DevX.com "])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config())
    assert "navya@devx.com" in readers


def test_gmail_readers_are_owners_plus_superusers():
    readers = acl.gmail_readers(["navya@devx.com"], "hindustantimes.com", _config())
    assert readers == {"navya@devx.com", "yash@devx.com"}


def test_gmail_readers_multiple_owners():
    readers = acl.gmail_readers(["a@devx.com", "b@devx.com"], "hindustantimes.com", _config())
    assert {"a@devx.com", "b@devx.com", "yash@devx.com"} == readers


def test_gmail_readers_no_owners_is_superusers_only():
    readers = acl.gmail_readers([], "hindustantimes.com", _config())
    assert readers == {"yash@devx.com"}


def test_no_superusers_configured(monkeypatch):
    _stub_members(monkeypatch, ["navya@devx.com"])
    readers = acl.slack_readers("C1", "hindustantimes.com", _config(superusers=[]))
    assert readers == {"navya@devx.com"}


def test_approved_viewers_can_read_slack_docs_without_membership(monkeypatch):
    _stub_members(monkeypatch, [])
    config = _config(accounts={"hindustantimes.com": AccountConfig(name="HT", approved_viewers=["analyst@devx.com"])})
    readers = acl.slack_readers("C1", "hindustantimes.com", config)
    assert "analyst@devx.com" in readers


def test_approved_viewers_can_read_gmail_docs_without_ownership():
    config = _config(accounts={"hindustantimes.com": AccountConfig(name="HT", approved_viewers=["analyst@devx.com"])})
    readers = acl.gmail_readers([], "hindustantimes.com", config)
    assert "analyst@devx.com" in readers


def test_approved_viewers_are_scoped_to_their_own_account(monkeypatch):
    _stub_members(monkeypatch, [])
    config = _config(
        accounts={
            "hindustantimes.com": AccountConfig(name="HT"),
            "other.com": AccountConfig(name="Other", approved_viewers=["analyst@devx.com"]),
        }
    )
    readers = acl.slack_readers("C1", "hindustantimes.com", config)
    assert "analyst@devx.com" not in readers
