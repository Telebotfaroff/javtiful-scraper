from app.catalog.studio_index import page_studios


def test_page_studios_returns_expected_page_and_count():
    studios = [{"name": f"Studio {i}", "url": f"https://example.test/{i}"} for i in range(23)]

    page, page_number, total_pages = page_studios(studios, 2, page_size=10)

    assert page_number == 2
    assert total_pages == 3
    assert len(page) == 10
    assert page[0]["name"] == "Studio 10"


def test_page_studios_clamps_out_of_range_pages():
    studios = [{"name": "Only", "url": "https://example.test/only"}]

    page, page_number, total_pages = page_studios(studios, 99, page_size=10)

    assert page_number == 1
    assert total_pages == 1
    assert page == studios
