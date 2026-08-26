"""CLI: register a user in state/users.json without the Gmail OAuth flow.

Access is derived from live Slack channel membership (plus config.superusers),
so registration only matters for Gmail: a user gets Gmail ingestion by
completing the OAuth flow, which registers them automatically. This script
exists to pre-register a user (gmail_secret stays null) or to inspect/repair
the registry by hand.

Needs PROJECT_ID and GCS_BUCKET set:

    PROJECT_ID=... GCS_BUCKET=... python -m scripts.upsert_user new-user@devx.com
"""

import argparse
import sys

from app.config_loader import upsert_user_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    args = parser.parse_args()

    email = args.email.strip().lower()

    def mutate(existing):
        if existing is None:
            return {"gmail_secret": None}
        return existing

    record = upsert_user_record(email, mutate)
    print(f"{email}: gmail_secret={record.get('gmail_secret')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
