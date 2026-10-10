import json

import pytest

from app.jobs.checkpoint_store import CheckpointStore


def test_new_store_starts_empty(tmp_path):
    store = CheckpointStore(tmp_path / "processed.json")
    assert store.summary() == {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "total": 0,
    }


def test_status_and_completion_survive_reload(tmp_path):
    path = tmp_path / "processed.json"
    store = CheckpointStore(path)
    store.mark_processing("video-1", title="Example")
    store.mark_completed(
        "video-1",
        title="Example",
        destination_message_id=123,
    )

    reloaded = CheckpointStore(path)
    assert reloaded.is_completed("video-1")
    assert reloaded.get("video-1")["destination_message_id"] == "123"
    assert reloaded.pending_ids() == []


def test_failed_and_interrupted_items_are_retryable(tmp_path):
    path = tmp_path / "processed.json"
    store = CheckpointStore(path)
    store.mark_failed("video-1", "network timeout")
    store.mark_processing("video-2", title="Interrupted")

    assert set(store.pending_ids()) == {"video-1", "video-2"}
    assert store.summary()["failed"] == 1
    assert store.summary()["processing"] == 1


def test_invalid_status_is_rejected(tmp_path):
    store = CheckpointStore(tmp_path / "processed.json")
    with pytest.raises(ValueError):
        store.mark("video-1", "unknown")


def test_invalid_database_is_rejected(tmp_path):
    path = tmp_path / "processed.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        CheckpointStore(path)
