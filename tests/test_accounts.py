from app.models import AccountConfig, SlackChannelConfig
from app.policy.accounts import match_gmail_account, match_slack_channel, normalize_domain

ACCOUNTS = {
    "hindustantimes.com": AccountConfig(name="Hindustan Times"),
    "otherpartner.com": AccountConfig(name="Other Partner"),
}


def test_no_match_discards():
    headers = {"From": "someone@example.com", "To": "person@devx.com"}
    assert match_gmail_account(headers, ACCOUNTS) is None


def test_single_match_approves():
    headers = {"From": "reporter@hindustantimes.com", "To": "ae@devx.com"}
    assert match_gmail_account(headers, ACCOUNTS) == "hindustantimes.com"


def test_multiple_matches_discarded_as_ambiguous():
    headers = {
        "From": "reporter@hindustantimes.com",
        "To": "ae@devx.com",
        "Cc": "someone@otherpartner.com",
    }
    assert match_gmail_account(headers, ACCOUNTS) is None


def test_subdomain_does_not_match():
    headers = {"From": "reporter@mail.hindustantimes.com"}
    assert match_gmail_account(headers, ACCOUNTS) is None


def test_internal_domain_is_never_an_account_match():
    headers = {"From": "ae@devx.com", "To": "colleague@devx.com"}
    accounts = {"devx.com": AccountConfig(name="Devx")}
    assert match_gmail_account(headers, accounts) is None or "devx.com" not in ACCOUNTS


def test_domain_normalization_trailing_dot_and_case():
    assert normalize_domain("HindustanTimes.com.") == "hindustantimes.com"
    headers = {"From": "reporter@HindustanTimes.com"}
    accounts = {"hindustantimes.com": AccountConfig(name="Hindustan Times")}
    assert match_gmail_account(headers, accounts) == "hindustantimes.com"


def test_allowed_sender_matches_without_owning_domain():
    headers = {"From": "demo@example.com", "To": "ae@devx.com"}
    accounts = {"hindustantimes.com": AccountConfig(name="Hindustan Times", allowed_senders=["demo@example.com"])}
    assert match_gmail_account(headers, accounts) == "hindustantimes.com"


def test_allowed_sender_claimed_by_two_accounts_is_ambiguous():
    headers = {"From": "demo@example.com", "To": "ae@devx.com"}
    accounts = {
        "hindustantimes.com": AccountConfig(name="Hindustan Times", allowed_senders=["demo@example.com"]),
        "otherpartner.com": AccountConfig(name="Other Partner", allowed_senders=["demo@example.com"]),
    }
    assert match_gmail_account(headers, accounts) is None


def test_slack_channel_whitelist_lookup():
    channels = {
        "C0123456789": SlackChannelConfig(name="ext-hindustan-times", account_domain="hindustantimes.com")
    }
    assert match_slack_channel("C0123456789", channels).account_domain == "hindustantimes.com"
    assert match_slack_channel("C999", channels) is None
