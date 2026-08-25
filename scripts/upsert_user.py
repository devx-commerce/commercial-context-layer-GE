"""CLI: add or update a user's team assignments in state/users.json (build spec
section 9 — this is how a Slack-only user, who never runs the Gmail OAuth flow,
gets registered). If --teams is omitted, a new user is assigned [default_team]
from the live config; an existing user's teams are left unchanged.

Needs PROJECT_ID and GCS_BUCKET set:

    PROJECT_ID=... GCS_BUCKET=... python -m scripts.upsert_user new-user@devx.com
    PROJECT_ID=... GCS_BUCKET=... python -m scripts.upsert_user ae@devx.com --teams enterprise-north
"""

import argparse
import sys

from app.config_loader import get_config, upsert_user_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--teams", help="comma-separated team names; defaults to [default_team] for new users")
    args = parser.parse_args()

    email = args.email.strip().lower()
    config = get_config()

    if args.teams:
        teams = [t.strip() for t in args.teams.split(",") if t.strip()]
        unknown = [t for t in teams if t not in config.teams]
        if unknown:
            print(f"ERROR: unknown team(s): {unknown}", file=sys.stderr)
            return 1
    else:
        teams = None

    def mutate(existing):
        if existing is None:
            return {"teams": teams or [config.default_team], "gmail_secret": None}
        if teams is not None:
            existing["teams"] = teams
        return existing

    record = upsert_user_record(email, mutate)
    print(f"{email}: teams={record['teams']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
