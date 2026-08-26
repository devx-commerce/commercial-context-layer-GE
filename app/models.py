"""Pydantic models for central config, user registry, operational state, and pending ops.

ACL model (v2): access mirrors live Slack channel membership plus a superusers
list. Slack-derived documents are readable by the current members of their
channel; Gmail-derived documents by the mailboxes they were ingested from.
Superusers read everything. No team hierarchy, no allow/deny lists.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AccountConfig(BaseModel):
    name: str


class SlackChannelConfig(BaseModel):
    name: str
    account_domain: str
    private: bool = False


class Config(BaseModel):
    version: int
    internal_domains: List[str]
    superusers: List[str] = Field(default_factory=list)
    poc_backfill_days: int
    attachment_max_bytes: int
    accounts: Dict[str, AccountConfig] = Field(default_factory=dict)
    slack_channels: Dict[str, SlackChannelConfig] = Field(default_factory=dict)


class UserRecord(BaseModel):
    gmail_secret: Optional[str] = None


# state/users.json is a mapping of email -> UserRecord.
UsersRegistry = Dict[str, UserRecord]


class GmailState(BaseModel):
    status: Literal["active", "reauthorization_required"]
    history_id: Optional[str] = None


class PendingOperation(BaseModel):
    """Minimal retry state written to pending/operations/<operation-id>.json.

    No message text, subjects, filenames, or account names. owner_email is the
    one identity field allowed: it names the onboarded mailbox a Gmail document
    came from, which is what its ACL is derived from.
    """

    operation: Literal["upsert", "delete", "fetch_slack_attachment", "resync_channel_acl"]
    document_id: str
    content_uri: Optional[str] = None

    # Present only for Gmail-sourced upserts: the onboarded mailbox this
    # document was ingested from (accumulated into state/owners/<doc>.json).
    owner_email: Optional[str] = None

    # Present for operation == "fetch_slack_attachment" (source retrieval IDs)
    # and for operation == "resync_channel_acl" (the channel to re-ACL).
    slack_file_id: Optional[str] = None
    slack_channel_id: Optional[str] = None
    parent_document_id: Optional[str] = None
