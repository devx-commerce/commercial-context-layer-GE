from app.models import AccountConfig, Config, SlackChannelConfig, UserRecord
from app.policy.config_validation import parse_config_json, validate


def _base_config(**overrides) -> Config:
    data = dict(
        version=1,
        internal_domains=["devx.com"],
        superusers=["yash@devx.com"],
        poc_backfill_days=7,
        attachment_max_bytes=20971520,
        accounts={"hindustantimes.com": AccountConfig(name="Hindustan Times")},
        slack_channels={},
    )
    data.update(overrides)
    return Config(**data)


def _base_users() -> dict:
    return {
        "specialist@devx.com": UserRecord(),
        "contractor@devx.com": UserRecord(),
    }


def test_valid_config_passes():
    assert validate(_base_config(), _base_users()) == []


def test_internal_domain_not_normalized():
    config = _base_config(internal_domains=["DevX.com"])
    assert any("internal_domains" in e for e in validate(config, _base_users()))


def test_superuser_not_normalized_email():
    config = _base_config(superusers=["Yash@DevX.com"])
    assert any("superusers" in e for e in validate(config, _base_users()))


def test_superuser_outside_internal_domains():
    config = _base_config(superusers=["yash@other.com"])
    errors = validate(config, _base_users())
    assert any("not in internal_domains" in e for e in errors)


def test_account_domain_not_normalized():
    config = _base_config(accounts={"Bad.Domain": AccountConfig(name="X")})
    errors = validate(config, _base_users())
    assert any("accounts" in e for e in errors)


def test_slack_channel_missing_account_domain():
    config = _base_config(
        slack_channels={
            "C1": SlackChannelConfig(name="ext-x", account_domain="unknown.com", private=False)
        }
    )
    errors = validate(config, _base_users())
    assert any("missing account domain" in e for e in errors)


def test_duplicate_slack_channel_key_detected_via_raw_json():
    raw = """
    {
      "version": 1,
      "internal_domains": ["devx.com"],
      "superusers": [],
      "poc_backfill_days": 7,
      "attachment_max_bytes": 100,
      "accounts": {},
      "slack_channels": {
        "C0123456789": {"name": "a", "account_domain": "x.com", "private": false},
        "C0123456789": {"name": "b", "account_domain": "x.com", "private": false}
      }
    }
    """
    parsed, errors = parse_config_json(raw)
    assert parsed is None
    assert any("duplicate key" in e for e in errors)


def test_user_email_not_normalized():
    errors = validate(_base_config(), {"Bad@DevX.com": UserRecord()})
    assert any("not a normalized email" in e for e in errors)


def test_gmail_user_bad_secret_resource_name():
    users = {
        "specialist@devx.com": UserRecord(gmail_secret="not-a-resource-name"),
        "contractor@devx.com": UserRecord(),
    }
    errors = validate(_base_config(), users)
    assert any("Secret Manager resource name" in e for e in errors)
