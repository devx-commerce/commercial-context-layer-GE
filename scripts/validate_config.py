"""CLI: validate a local config.json (optionally cross-checked against a local
users.json) against build spec section 7's rules. Exits non-zero on failure.

No GCP access needed — pure local validation, so this works with zero env vars:

    python -m scripts.validate_config config.json --users users.json
"""

import argparse
import json
import sys

from app.models import Config, UserRecord
from app.policy.config_validation import parse_config_json, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path")
    parser.add_argument("--users", help="path to a local users.json to cross-validate against")
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

    users = None
    if args.users:
        with open(args.users, "r", encoding="utf-8") as f:
            users_raw = json.load(f)
        try:
            users = {email: UserRecord.model_validate(v) for email, v in users_raw.items()}
        except Exception as exc:
            print(f"ERROR: invalid users.json shape: {exc}", file=sys.stderr)
            return 1

    errors = validate(config, users)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print("config is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
