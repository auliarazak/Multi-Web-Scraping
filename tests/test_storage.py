import os
import sqlite3
import tempfile
import unittest
import sys
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = storage.DB_PATH
        storage.DB_PATH = os.path.join(self.tmp.name, "test.db")
        storage.init_db()

    def tearDown(self):
        storage.DB_PATH = self.previous
        self.tmp.cleanup()

    def save(self, keyword, source="Tokopedia"):
        row = {"source": source, "keyword": keyword, "title": "Produk",
               "url": "https://example.com/product", "harga": "100"}
        self.assertEqual(storage.save_rows_to_db([row]), 1)
        storage.update_cache(source, keyword, row_count=1)

    def test_one_item_can_belong_to_multiple_searches(self):
        self.save("sepatu")
        self.save("sepatu hitam")
        for keyword in ("sepatu", "sepatu hitam"):
            rows, fresh = storage.get_cached_rows("Tokopedia", keyword)
            self.assertTrue(fresh)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["harga"], "100")

    def test_reviews_locations_remain_distinct(self):
        self.save("roti||Padang", "Google Reviews")
        self.save("roti||Bandung", "Google Reviews")
        for location in ("Padang", "Bandung"):
            rows, fresh = storage.get_cached_rows("Google Reviews", "roti||" + location)
            self.assertTrue(fresh)
            self.assertEqual(len(rows), 1)
        self.assertEqual(storage.get_cached_rows("Google Reviews", "roti"), ([], False))

    def test_failed_batch_rolls_back_item_and_details(self):
        with closing(sqlite3.connect(storage.DB_PATH)) as conn, conn:
            conn.execute("DROP TABLE ecommerce_detail")
        with self.assertRaisesRegex(RuntimeError, "Gagal menyimpan"):
            storage.save_rows_to_db([{"source": "Tokopedia", "keyword": "x",
                                      "url": "https://example.com/a"}])
        with closing(sqlite3.connect(storage.DB_PATH)) as conn, conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM items").fetchone()[0], 0)

    def test_old_database_migrates_recorded_keyword(self):
        with closing(sqlite3.connect(storage.DB_PATH)) as conn, conn:
            conn.execute("DROP TABLE search_results")
            conn.execute("PRAGMA user_version = 1")
            conn.execute("INSERT INTO items(source, keyword, title, url, scraped_at) "
                         "VALUES ('Tokopedia', ' Sepatu ', 'x', 'https://example.com/x', "
                         "datetime('now', 'localtime'))")
        storage.update_cache("Tokopedia", "sepatu", row_count=1)
        storage.init_db()
        rows, fresh = storage.get_cached_rows("Tokopedia", "sepatu")
        self.assertTrue(fresh)
        self.assertEqual(len(rows), 1)

    def test_migrates_scheduled_job_and_persists_location(self):
        job_id = storage.add_scheduled_job("Google Reviews", "roti")
        with closing(sqlite3.connect(storage.DB_PATH)) as conn, conn:
            conn.execute("ALTER TABLE scheduled_jobs DROP COLUMN location")
            conn.execute("ALTER TABLE ecommerce_detail DROP COLUMN shop_name")
            conn.execute("PRAGMA user_version = 2")
        storage.init_db()
        self.assertEqual(storage.get_scheduled_job(job_id)["location"], "")
        storage.update_scheduled_job(job_id, location="Bandung")
        self.assertEqual(storage.get_scheduled_job(job_id)["location"], "Bandung")

    def test_store_name_is_available_for_export_after_cache_reload(self):
        row = {"source": "Tokopedia", "keyword": "sepatu", "title": "Sepatu",
               "url": "https://example.com/sepatu", "shop_name": "Toko Contoh"}
        storage.save_rows_to_db([row])
        storage.update_cache("Tokopedia", "sepatu", row_count=1)
        rows, fresh = storage.get_cached_rows("Tokopedia", "sepatu")
        self.assertTrue(fresh)
        self.assertEqual(rows[0]["shop_name"], "Toko Contoh")

    def test_v3_jobs_get_browser_default_without_reactivating_jobs(self):
        tok = storage.add_scheduled_job("Tokopedia", "celana")
        other = storage.add_scheduled_job("Lazada", "celana")
        storage.set_job_active(tok, False)
        before = storage.get_scheduled_job(tok)
        with closing(sqlite3.connect(storage.DB_PATH)) as conn, conn:
            conn.execute("ALTER TABLE scheduled_jobs DROP COLUMN headless")
            conn.execute("PRAGMA user_version = 3")
        storage.init_db()
        self.assertEqual(storage.get_scheduled_job(tok), dict(before, headless=0))
        self.assertEqual(storage.get_scheduled_job(other)["headless"], 1)
        storage.update_scheduled_job(tok, headless=1)
        storage.init_db()
        self.assertEqual(storage.get_scheduled_job(tok)["headless"], 1)


if __name__ == "__main__":
    unittest.main()
