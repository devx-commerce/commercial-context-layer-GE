from app.models import AccountConfig, Config, TeamConfig, UserRecord
from app.policy.config_validation import parse_config_json, validate


def _base_config(**overrides) -> Config:
    data = dict(
        version=1,
        internal_domains=["devx.com"],
        default_team="base",
        poc_backfill_days=7,
        attachment_max_bytes=20971520,
        teams={
            "commercial": TeamConfig(parent=None),
            "enterprise": TeamConfig(parent="commercial"),
            "enterprise-north": TeamConfig(parent="enterprise"),
            "enterprise-south": TeamConfig(parent="enterprise"),
            "base": TeamConfig(parent="commercial"),
        },
        accounts={
            "hindustantimes.com": AccountConfig(
                name="Hindustan Times",
                teams=["enterprise-north"],
                allow_users=["specialist@devx.com"],
                deny_users=["contractor@devx.com"],
            )
        },
        slack_channels={},
    )
    data.update(overrides)
    return Config(**data)


def _base_users() -> dict:
    return {
        "specialist@devx.com": UserRecord(teams=["enterprise-north"]),
        "contractor@devx.com": UserRecord(teams=["enterprise-north"]),
    }


def test_valid_config_passes():
    assert validate(_base_config(), _base_users()) == []


def test_internal_domain_not_normalized():
    config = _base_config(internal_domains=["DevX.com"])
    assert any("internal_domains" in e for e in validate(config, _base_users()))


def test_team_missing_parent():
    config = _base_config(teams={"base": TeamConfig(parent="ghost")})
    errors = validate(config, {})
    assert any("missing" in e for e in errors)


def test_team_cycle_detected():
    config = _base_config(
        teams={
            "a": TeamConfig(parent="b"),
            "b": TeamConfig(parent="a"),
        },
        default_team="a",
        accounts={},
    )
    errors = validate(config, {})
    assert any("cycle" in e for e in errors)


def test_default_team_missing():
    config = _base_config(default_team="ghost")
    errors = validate(config, _base_users())
    assert any("default_team" in e for e in errors)


def test_default_team_not_leaf():
    config = _base_config(default_team="commercial")
    errors = validate(config, _base_users())
    assert any("leaf" in e for e in errors)


def test_account_references_missing_team():
    config = _base_config(
        accounts={"hindustantimes.com": AccountConfig(name="HT", teams=["no-such-team"])}
    )
    errors = validate(config, {})
    assert any("missing team" in e for e in errors)


def test_allow_user_not_registered():
    config = _base_config()
    users = {"contractor@devx.com": UserRecord(teams=["enterprise-north"])}
    errors = validate(config, users)
    assert any("not a registered internal user" in e for e in errors)


def test_slack_channel_missing_account_domain():
    from app.models import SlackChannelConfig

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
      "default_team": "base",
      "poc_backfill_days": 7,
      "attachment_max_bytes": 100,
      "teams": {"base": {"parent": null}},
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


def test_gmail_user_bad_secret_resource_name():
    config = _base_config()
    users = {
        "specialist@devx.com": UserRecord(teams=["enterprise-north"], gmail_secret="not-a-resource-name"),
        "contractor@devx.com": UserRecord(teams=["enterprise-north"]),
    }
    errors = validate(config, users)
    assert any("Secret Manager resource name" in e for e in errors)
