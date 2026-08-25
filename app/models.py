"""Pydantic models for central config, user registry, operational state, and pending ops.

These mirror the JSON shapes fixed in the build spec (sections 6, 7, 17) exactly —
no extra fields are introduced beyond what the spec's strict storage contract allows.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TeamConfig(BaseModel):
    parent: Optional[str] = None


class AccountConfig(BaseModel):
    name: str
    teams: List[str]
    allow_users: List[str] = Field(default_factory=list)
    deny_users: List[str] = Field(default_factory=list)


class SlackChannelConfig(BaseModel):
    name: str
    account_domain: str
    private: bool = False


class Config(BaseModel):
    version: int
    internal_domains: List[str]
    default_team: str
    poc_backfill_days: int
    attachment_max_bytes: int
    teams: Dict[str, TeamConfig]
    accounts: Dict[str, AccountConfig] = Field(default_factory=dict)
    slack_channels: Dict[str, SlackChannelConfig] = Field(default_factory=dict)


class UserRecord(BaseModel):
    teams: List[str]
    gmail_secret: Optional[str] = None


# state/users.json is a mapping of email -> UserRecord.
UsersRegistry = Dict[str, UserRecord]


class GmailState(BaseModel):
    status: Literal["active", "reauthorization_required"]
    history_id: Optional[str] = None


class PendingOperation(BaseModel):
    """Minimal retry state written to pending/operations/<operation-id>.json.

    Only the fields the spec explicitly allows (section 6, section 14) are present.
    No message text, subjects, participants, filenames, or account names.
    """

    operation: Literal["upsert", "delete", "fetch_slack_attachment"]
    document_id: str
    content_uri: Optional[str] = None

    # Present only for operation == "fetch_slack_attachment" (section 11, point 11):
    # the source retrieval IDs required to finish an approved attachment download.
    slack_file_id: Optional[str] = None
    slack_channel_id: Optional[str] = None
    parent_document_id: Optional[str] = None
