from app.storage.processed import ProcessedStore


def make_store(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("PROCESSED_DB_BRANCH", raising=False)
    store = ProcessedStore()
    store.local_path = tmp_path / "telegram_upload_history.json"
    return store


def test_summary_counts_completed_records(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    store.mark_completed("https://example.test/a", "CODE-1", "First")
    store.mark_completed("https://example.test/b", "CODE-2", "Second")

    assert store.summary() == {"total": 2, "completed": 2, "other": 0}


def test_recent_completed_is_bounded_and_sanitized(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    store.mark_completed(
        "https://example.test/private-source",
        "CODE-1",
        "Sample title",
        destination="telegram",
        message_ids=[12345],
    )

    recent = store.recent_completed(1)
    assert len(recent) == 1
    assert recent[0]["title"] == "Sample title"
    assert recent[0]["code"] == "CODE-1"
    assert "url" not in recent[0]
    assert "telegram_message_ids" not in recent[0]
