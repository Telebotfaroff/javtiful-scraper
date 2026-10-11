from app.uploaders import telegram as telegram_uploader


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def _patch_client(monkeypatch):
    monkeypatch.setattr(telegram_uploader, "Client", FakeClient)
    monkeypatch.setenv("TELEGRAM_UPLOAD_CLIENTS", "1")
    monkeypatch.delenv("TELEGRAM_UPLOAD_SESSIONS", raising=False)


def test_telegram_upload_defaults_to_four_transmissions(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.delenv("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS", raising=False)

    uploader = telegram_uploader.TelegramUploader(
        api_id=12345,
        api_hash="test-hash",
        bot_token="123:test-token",
    )

    assert uploader.max_concurrent_transmissions == 4
    assert uploader._clients[0].kwargs["max_concurrent_transmissions"] == 4
    assert uploader._clients[0].kwargs["sleep_threshold"] == 60


def test_telegram_upload_concurrency_can_be_configured(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setenv("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS", "8")

    uploader = telegram_uploader.TelegramUploader(
        api_id=12345,
        api_hash="test-hash",
        bot_token="123:test-token",
    )

    assert uploader.max_concurrent_transmissions == 8


def test_telegram_upload_rejects_unreasonable_concurrency(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setenv("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS", "9")

    try:
        telegram_uploader.TelegramUploader(
            api_id=12345,
            api_hash="test-hash",
            bot_token="123:test-token",
        )
    except ValueError as exc:
        assert "between 1 and 8" in str(exc)
    else:
        raise AssertionError("Concurrency above 8 must be rejected")
