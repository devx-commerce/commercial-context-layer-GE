"""Regression test for the users.json upsert-retry loop.

This exists because a prior version of the code caught the wrong exception
(google.api_core.exceptions.FailedPrecondition, a gRPC/HTTP-400 error) instead
of the one GCS actually raises on a lost if_generation_match race
(PreconditionFailed, HTTP 412) — which would have let a concurrent-write
conflict crash the request instead of retrying.
"""

from app.config_loader import upsert_user_record
from app.storage import gcs


def test_upsert_user_record_retries_past_a_generation_conflict(monkeypatch):
    state = {"data": {}, "generation": 0}
    attempts = {"count": 0}

    def fake_read_json(path):
        return gcs.JsonObject(data=dict(state["data"]), generation=state["generation"])

    def fake_write_json(path, data, if_generation_match=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise gcs.PreconditionFailed("lost the race")
        assert if_generation_match == state["generation"]
        state["data"] = data
        state["generation"] += 1
        return state["generation"]

    monkeypatch.setattr(gcs, "read_json", fake_read_json)
    monkeypatch.setattr(gcs, "write_json", fake_write_json)

    def mutate(existing):
        assert existing is None
        return {"gmail_secret": None}

    record = upsert_user_record("new-user@devx.com", mutate)

    assert attempts["count"] == 2  # first attempt lost the race, second succeeded
    assert record == {"gmail_secret": None}
    assert state["data"]["new-user@devx.com"] == record
