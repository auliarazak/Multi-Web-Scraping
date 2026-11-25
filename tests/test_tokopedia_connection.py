import unittest
from unittest.mock import Mock, patch

from scraper import tokopedia


class TokopediaConnectionTests(unittest.TestCase):
    def test_navigation_recovers_from_one_transport_error(self):
        page = Mock()
        page.goto.side_effect = [tokopedia.PWError("net::ERR_HTTP2_PROTOCOL_ERROR"), None]
        self.assertTrue(tokopedia._open_search(page, "https://example.invalid", None))
        self.assertEqual(page.goto.call_count, 2)

    def test_later_navigation_failure_returns_existing_products_as_partial(self):
        product = {"title": "Mouse", "harga": "100", "url": "https://example.invalid/a"}
        error = tokopedia._NavigationConnectionError("ERR_HTTP2_PROTOCOL_ERROR")
        partial = Mock()
        with patch.object(tokopedia, "_scrape_tokopedia_single",
                          side_effect=[[product], error]) as fetch:
            rows = tokopedia.scrape_tokopedia(keyword="mouse", limit=5, on_partial=partial)
        self.assertEqual([row["title"] for row in rows], ["Mouse"])
        self.assertEqual(fetch.call_count, 2)
        partial.assert_called_once_with(str(error), 1)
