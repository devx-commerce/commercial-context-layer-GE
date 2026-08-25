"""Secret Manager helpers: access existing secrets, and get-or-create per-user secrets.

Per-user Gmail refresh-token secrets are created dynamically during OAuth onboarding
(build spec section 9) — this requires the running service account to hold
secretmanager.admin (or secrets.create + secrets.versions.add) at the project level.
"""

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import secretmanager

from app.settings import settings

_client = None


def _get_client() -> secretmanager.SecretManagerServiceClient:
    global _client
    if _client is None:
        _client = secretmanager.SecretManagerServiceClient()
    return _client


def access_latest(secret_resource_name: str) -> str:
    """secret_resource_name is 'projects/PROJECT_ID/secrets/NAME'."""
    client = _get_client()
    response = client.access_secret_version(
        name=f"{secret_resource_name}/versions/latest"
    )
    return response.payload.data.decode("utf-8")


def get_or_create_user_secret(secret_id: str) -> str:
    """Ensure projects/<project>/secrets/<secret_id> exists; return its resource name."""
    client = _get_client()
    parent = f"projects/{settings.project_id}"
    resource_name = f"{parent}/secrets/{secret_id}"
    try:
        client.create_secret(
            parent=parent,
            secret_id=secret_id,
            secret={"replication": {"automatic": {}}},
        )
    except AlreadyExists:
        pass
    return resource_name


def add_version(secret_resource_name: str, value: str) -> None:
    client = _get_client()
    client.add_secret_version(
        parent=secret_resource_name,
        payload={"data": value.encode("utf-8")},
    )


def secret_exists(secret_resource_name: str) -> bool:
    client = _get_client()
    try:
        client.get_secret(name=secret_resource_name)
        return True
    except NotFound:
        return False
