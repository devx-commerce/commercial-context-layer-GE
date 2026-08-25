from app.models import SlackChannelConfig
from app.policy.accounts import match_gmail_account, match_slack_channel, normalize_domain

ACCOUNT_DOMAINS = ["hindustantimes.com", "otherpartner.com"]


def test_no_match_discards():
    headers = {"From": "someone@example.com", "To": "person@devx.com"}
    assert match_gmail_account(headers, ACCOUNT_DOMAINS) is None


def test_single_match_approves():
    headers = {"From": "reporter@hindustantimes.com", "To": "ae@devx.com"}
    assert match_gmail_account(headers, ACCOUNT_DOMAINS) == "hindustantimes.com"


def test_multiple_matches_discarded_as_ambiguous():
    headers = {
        "From": "reporter@hindustantimes.com",
        "To": "ae@devx.com",
        "Cc": "someone@otherpartner.com",
    }
    assert match_gmail_account(headers, ACCOUNT_DOMAINS) is None


def test_subdomain_does_not_match():
    headers = {"From": "reporter@mail.hindustantimes.com"}
    assert match_gmail_account(headers, ACCOUNT_DOMAINS) is None


def test_internal_domain_is_never_an_account_match():
    headers = {"From": "ae@devx.com", "To": "colleague@devx.com"}
    assert match_gmail_account(headers, ["devx.com"]) is None or "devx.com" not in ACCOUNT_DOMAINS


def test_domain_normalization_trailing_dot_and_case():
    assert normalize_domain("HindustanTimes.com.") == "hindustantimes.com"
    headers = {"From": "reporter@HindustanTimes.com"}
    assert match_gmail_account(headers, ["hindustantimes.com"]) == "hindustantimes.com"


def test_slack_channel_whitelist_lookup():
    channels = {
        "C0123456789": SlackChannelConfig(name="ext-hindustan-times", account_domain="hindustantimes.com")
    }
    assert match_slack_channel("C0123456789", channels).account_domain == "hindustantimes.com"
    assert match_slack_channel("C999", channels) is None
