import json

import pytest

from app.jobs.resumable_manifest_runner import load_manifest


def test_loads_valid_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({
            "items": [
                {
                    "id": "media-1",
                    "url": "https://cdn.example.test/video.mp4",
                    "title": "Sample",
                }
            ]
        }),
        encoding="utf-8",
    )

    items = load_manifest(path)
    assert len(items) == 1
    assert items[0]["id"] == "media-1"
    assert items[0]["title"] == "Sample"


def test_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({
            "items": [
                {"id": "same", "url": "https://cdn.example.test/a.mp4"},
                {"id": "same", "url": "https://cdn.example.test/b.mp4"},
            ]
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate"):
        load_manifest(path)


def test_rejects_non_http_url(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"items": [{"id": "media-1", "url": "file:///tmp/video.mp4"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HTTP"):
        load_manifest(path)


def test_rejects_missing_items_array(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"media": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="items"):
        load_manifest(path)
