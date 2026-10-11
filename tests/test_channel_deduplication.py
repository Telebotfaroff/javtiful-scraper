from app.extractor.channel import JavtifulChannelExtractor


def test_deduplicates_by_normalized_video_code():
    items = [
        {"code": "abw_001", "post_url": "https://example.test/video/1", "title": "ABW-001 One"},
        {"code": "ABW-001", "post_url": "https://example.test/video/2", "title": "ABW-001 Duplicate"},
        {"code": "ABW-002", "post_url": "https://example.test/video/3", "title": "ABW-002 Two"},
    ]

    unique, duplicates = JavtifulChannelExtractor.deduplicate_items(items)

    assert len(unique) == 2
    assert duplicates == 1
    assert unique[0]["post_url"] == "https://example.test/video/1"
    assert unique[1]["code"] == "ABW-002"


def test_deduplicates_canonical_urls_when_code_is_missing():
    items = [
        {"code": None, "post_url": "https://example.test/video/123?utm_source=one", "title": "First"},
        {"code": None, "post_url": "https://EXAMPLE.test/video/123/#player", "title": "Duplicate"},
        {"code": None, "post_url": "https://example.test/video/456", "title": "Second"},
    ]

    unique, duplicates = JavtifulChannelExtractor.deduplicate_items(items)

    assert len(unique) == 2
    assert duplicates == 1
    assert unique[0]["title"] == "First"
    assert unique[1]["title"] == "Second"


def test_extracts_code_from_title_when_item_code_is_missing():
    items = [
        {"post_url": "https://example.test/post/1", "title": "ABW-004 Example"},
        {"post_url": "https://example.test/post/2", "title": "ABW_004 Another copy"},
    ]

    unique, duplicates = JavtifulChannelExtractor.deduplicate_items(items)

    assert len(unique) == 1
    assert duplicates == 1
