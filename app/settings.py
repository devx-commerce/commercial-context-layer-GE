"""Runtime environment configuration.

Everything here is deployment wiring (project/bucket/audience/secret names), never
business data. Secret *values* (OAuth client secret, Slack tokens, the state-signing
key) are fetched from Secret Manager at startup using the resource names below —
see app.storage.secret_manager.

Only project_id and gcs_bucket are required to import this module (they're needed
by every code path, including the standalone scripts under scripts/). Everything
else is Optional and only required by the parts of the app that actually use it
(the deployed FastAPI service needs all of it; a script like validate_config.py
needs none of it) — call `require()` at the point of use rather than assuming
a field is set.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_id: str
    gcs_bucket: str

    # Audience Cloud Scheduler's OIDC token must carry (the Cloud Run service URL),
    # and the email of the service account Cloud Scheduler authenticates as.
    oidc_audience: Optional[str] = None
    scheduler_service_account_email: Optional[str] = None

    # Secret Manager resource names (projects/<id>/secrets/<name>), not values.
    gmail_oauth_client_secret: Optional[str] = None
    oauth_state_signing_secret: Optional[str] = None
    slack_bot_token_secret: Optional[str] = None
    slack_signing_secret_secret: Optional[str] = None

    gmail_oauth_redirect_uri: Optional[str] = None

    discoveryengine_location: str = "global"
    discoveryengine_collection: str = "default_collection"
    discoveryengine_data_store_id: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env")


def require(value: Optional[str], field_name: str) -> str:
    if value is None:
        raise RuntimeError(f"missing required setting: {field_name}")
    return value


settings = Settings()  # type: ignore[call-arg]
