"""Load central config and the user registry from GCS.

Config is small and rarely changes, so every call reads the current atomic
object straight from GCS rather than caching across requests — simplest way to
avoid a stale-cache bug, and cheap enough for a POC. Both loaders validate
before returning and raise ConfigError on any problem, which callers must treat
as fail-closed (build spec section 18): do not ingest on missing/invalid config.
"""

from typing import Callable, Dict, Optional, Tuple

from app.models import Config, UserRecord
from app.policy.config_validation import parse_config_json, validate
from app.storage import gcs

CONFIG_PATH = "config/config.json"
USERS_PATH = "state/users.json"


class ConfigError(Exception):
    pass


def load_config_and_users() -> Tuple[Config, Dict[str, UserRecord], int]:
    """Returns (config, users, users_generation) for use by callers that need to
    upsert users.json with a generation-match precondition afterwards."""
    # Parsed from the raw bytes (not via gcs.read_json) so that
    # parse_config_json's duplicate-key check — the section 7 rule that a Slack
    # channel can't be declared twice — can still catch a duplicate that a
    # plain json.loads would have already silently collapsed.
    raw_bytes = gcs.read_bytes(CONFIG_PATH)
    if raw_bytes is None:
        raise ConfigError(f"{CONFIG_PATH} does not exist")

    parsed, parse_errors = parse_config_json(raw_bytes.decode("utf-8"))
    if parse_errors:
        raise ConfigError(f"invalid {CONFIG_PATH}: {parse_errors}")

    try:
        config = Config.model_validate(parsed)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"invalid {CONFIG_PATH} shape: {exc}") from exc

    users_obj = gcs.read_json(USERS_PATH)
    users_raw = users_obj.data if users_obj is not None else {}
    users_generation = users_obj.generation if users_obj is not None else 0
    try:
        users = {email: UserRecord.model_validate(v) for email, v in users_raw.items()}
    except Exception as exc:
        raise ConfigError(f"invalid {USERS_PATH} shape: {exc}") from exc

    errors = validate(config, users)
    if errors:
        raise ConfigError(f"config validation failed: {errors}")

    return config, users, users_generation


def get_config() -> Config:
    config, _, _ = load_config_and_users()
    return config


def upsert_user_record(
    email: str,
    mutate: Callable[[Optional[dict]], dict],
    max_retries: int = 5,
) -> dict:
    """Read-modify-write state/users.json under a generation-match precondition,
    retrying on lost races. `mutate` receives the user's current raw record dict
    (or None if new) and returns the new raw record dict to store.
    """
    for _ in range(max_retries):
        obj = gcs.read_json(USERS_PATH)
        users_raw = dict(obj.data) if obj is not None else {}
        generation = obj.generation if obj is not None else 0

        new_record = mutate(users_raw.get(email))
        users_raw[email] = new_record

        try:
            gcs.write_json(USERS_PATH, users_raw, if_generation_match=generation)
            return new_record
        except gcs.PreconditionFailed:
            continue
    raise ConfigError(f"failed to upsert user {email!r} after {max_retries} retries (concurrent update)")
