from app.storage.neon_processed import NeonProcessedStore, ProcessedStoreError


def test_neon_store_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        NeonProcessedStore()
    except ProcessedStoreError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("Neon store must require DATABASE_URL")


def test_neon_key_normalization_is_stable():
    assert NeonProcessedStore.key_for("https://example.test/a?tracking=1", "abw_001") == "code:ABW-001"
    assert NeonProcessedStore.key_for("https://example.test/a?tracking=1") == NeonProcessedStore.key_for(
        "https://example.test/a#section"
    )
