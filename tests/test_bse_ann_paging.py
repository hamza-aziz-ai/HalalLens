"""Announcement paging: every page is followed, with a stop on a repeated page
and a hard page cap, for both the daily feed and company announcements."""

from crawler.bse_ann import BSEAnnouncementsFetcher


def _fetcher(pages):
    fetcher = BSEAnnouncementsFetcher.__new__(BSEAnnouncementsFetcher)
    fetcher.api_base = "https://example.invalid/api"
    calls = []

    def fake_request(url, params):
        calls.append(params["pageno"])
        index = params["pageno"] - 1
        return {"Table": pages[index]} if index < len(pages) else {"Table": []}

    fetcher._make_request = fake_request
    return fetcher, calls


def test_company_announcements_follow_every_page():
    fetcher, calls = _fetcher([[{"id": 1}, {"id": 2}], [{"id": 3}], []])
    rows = fetcher.get_company_announcements("500325", "20261001", "20261028")
    assert [row["id"] for row in rows] == [1, 2, 3]
    assert calls == [1, 2, 3]


def test_paging_stops_when_the_server_repeats_a_page():
    same = [{"id": 1}]
    fetcher, calls = _fetcher([same, same, same])
    assert fetcher.get_company_announcements("500325", "20261001", "20261028") == same
    assert calls == [1, 2]


def test_paging_stops_at_the_page_cap():
    fetcher, calls = _fetcher([[{"id": n}] for n in range(10)])
    rows = fetcher._fetch_pages("u", {}, max_pages=3)
    assert [row["id"] for row in rows] == [0, 1, 2]
    assert calls == [1, 2, 3]


def test_failed_request_returns_no_rows():
    fetcher, _ = _fetcher([])
    fetcher._make_request = lambda url, params: None
    assert fetcher.get_company_announcements("500325", "20261001", "20261028") == []
