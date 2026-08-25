import os

# app.settings.Settings requires these two at import time (everything else it
# defines is Optional, precisely so tests/scripts that don't touch GCP can skip
# them). Set harmless placeholders here so any test module is free to import
# app.storage.gcs / app.config_loader without needing real GCP access.
os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
