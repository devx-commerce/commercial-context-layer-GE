"""CLI: validate a local config.json against the live state/users.json in GCS,
then upload it to config/config.json with a generation-match precondition.
Refuses to upload on any validation failure.

Needs PROJECT_ID and GCS_BUCKET set (see README):

    PROJECT_ID=... GCS_BUCKET=... python -m scripts.upload_config config.json
"""

import argparse
import sys

from app.config_loader import CONFIG_PATH, USERS_PATH
from app.models import Config, UserRecord
from app.policy.config_validation import parse_config_json, validate
from app.storage import gcs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path")
    args = parser.parse_args()

    with open(args.config_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    parsed, parse_errors = parse_config_json(raw_text)
    if parse_errors:
        for err in parse_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    try:
        config = Config.model_validate(parsed)
    except Exception as exc:
        print(f"ERROR: invalid config shape: {exc}", file=sys.stderr)
        return 1

    users_obj = gcs.read_json(USERS_PATH)
    users_raw = users_obj.data if users_obj is not None else {}
    users = {email: UserRecord.model_validate(v) for email, v in users_raw.items()}

    errors = validate(config, users)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    existing = gcs.read_json(CONFIG_PATH)
    generation = existing.generation if existing is not None else 0
    gcs.write_json(CONFIG_PATH, parsed, if_generation_match=generation)
    print(f"uploaded {CONFIG_PATH} (generation {generation} -> new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
