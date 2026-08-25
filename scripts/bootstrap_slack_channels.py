"""CLI: join every configured public Slack channel (build spec section 9).
Private channels are never auto-joined — a channel member must invite the bot;
this script just reports which ones still need that invite.

Needs PROJECT_ID, GCS_BUCKET, and SLACK_BOT_TOKEN_SECRET set:

    PROJECT_ID=... GCS_BUCKET=... SLACK_BOT_TOKEN_SECRET=... python -m scripts.bootstrap_slack_channels
"""

import sys

from slack_sdk.errors import SlackApiError

from app.config_loader import get_config
from app.sources import slack_client


def main() -> int:
    config = get_config()
    had_error = False

    for channel_id, channel in config.slack_channels.items():
        if channel.private:
            print(f"{channel_id} ({channel.name}): private — invite_required")
            continue
        try:
            slack_client.join_channel(channel_id)
            print(f"{channel_id} ({channel.name}): joined")
        except SlackApiError as exc:
            had_error = True
            print(f"{channel_id} ({channel.name}): failed to join: {exc.response.get('error')}", file=sys.stderr)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
