import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scrape_pipeline


def identity_row(market, keyword, row):
    return dict(row, source=market, keyword=keyword)


class PipelineTests(unittest.TestCase):
    @patch("scrape_pipeline.update_cache")
    @patch("scrape_pipeline.save_rows_to_db", side_effect=RuntimeError("disk error"))
    def test_save_failure_never_marks_cache_fresh(self, save, update):
        with self.assertRaisesRegex(RuntimeError, "disk error"):
            scrape_pipeline.run_pipeline(
                "Tokopedia", "keyword", "sepatu", 10, True, "",
                lambda: [{"url": "https://example.com/x"}], identity_row,
                identity_row, lambda row: row)
        update.assert_not_called()

    @patch("scrape_pipeline.get_cached_rows_by_url")
    def test_url_cache_hit_does_not_scrape_again(self, cached):
        cached.return_value = ([{"url": "https://example.com/x"}], True)
        def fail_scrape():
            raise AssertionError("cache URL should be used")
        rows, source = scrape_pipeline.run_pipeline(
            "Tokopedia", "url", "https://example.com/x", 10, False, "",
            fail_scrape, identity_row, identity_row, lambda row: row)
        self.assertEqual(source, "database")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
