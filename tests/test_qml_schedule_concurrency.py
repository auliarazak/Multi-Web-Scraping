import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

import storage
from qml_prototype.backend import Backend


class ScheduleConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(storage, "DB_PATH", os.path.join(directory, "test.db")))
        storage.init_db()
        self.job = storage.add_scheduled_job("News", "scheduled", interval_minutes=2,
                                             next_run_at="2000-01-01T00:00:00")
        self.backend = Backend()
        self.schedule = self.backend.schedule
        self.started = {key: threading.Event() for key in ("manual", "scheduled")}
        self.release = {key: threading.Event() for key in self.started}
        self.tokens = {}
        self.enterContext(patch.object(self.backend, "_scrape_from_web", self.fetch))

    def fetch(self, source, mode, keyword, *args, **kwargs):
        self.tokens[keyword] = kwargs.get("stop_event", self.backend._stop_event)
        self.started[keyword].set()
        if not self.release[keyword].wait(5):
            raise RuntimeError("Test worker timed out")
        return [{"title": keyword, "url": "https://example.invalid/" + keyword}]

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.qt.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Qt worker did not reach the expected state")

    def tearDown(self):
        self.schedule.setAutomatic(False)
        for event in self.release.values():
            event.set()
        self.wait_for(lambda: not self.backend.running and not self.schedule.activeId)
        self.backend.shutdown()

    def manual(self, source):
        self.backend.setSource(source)
        self.backend.scrape("manual", "keyword", 1, True, True, "")

    def make_due(self, job_id):
        storage.update_scheduled_job(job_id, next_run_at="2000-01-01T00:00:00")
        self.schedule.check_due_jobs()

    def test_tokopedia_saved_browser_mode_used_by_timer_and_run_now(self):
        self.schedule.setAutomatic(True)
        job_id = storage.add_scheduled_job("Tokopedia", "celana")
        with patch.object(self.backend, "_scrape_from_web", return_value=[]) as fetch:
            self.make_due(job_id)
            self.wait_for(lambda: fetch.called and not self.schedule.activeId)
            self.assertIs(fetch.call_args.args[4], False)
            fetch.reset_mock()
            self.assertEqual(self.schedule.saveJob(job_id, "Tokopedia", "keyword",
                                                   "celana", 60, 1, "", True), "")
            self.assertEqual(self.schedule.runNow(job_id), "")
            self.wait_for(lambda: fetch.called and not self.schedule.activeId)
            self.assertIs(fetch.call_args.args[4], True)

    def test_saved_overdue_job_waits_for_opt_in_and_its_interval(self):
        self.qt.processEvents()
        self.schedule.check_due_jobs()
        self.assertFalse(self.schedule.automaticEnabled)
        self.assertFalse(self.schedule.activeId)
        self.assertTrue(self.schedule.runNow(self.job))
        before = datetime.now().replace(microsecond=0)
        self.assertEqual(self.schedule.setAutomatic(True), "")
        next_time = datetime.fromisoformat(storage.get_scheduled_job(self.job)["next_run_at"])
        self.assertGreaterEqual((next_time - before).total_seconds(), 120)
        self.qt.processEvents()
        self.assertFalse(self.schedule.activeId)
        self.schedule.setAutomatic(False)
        self.make_due(self.job)
        self.assertFalse(self.schedule.activeId)
        self.assertEqual(storage.list_crawl_runs(), [])

    def test_manual_other_source_can_start_during_schedule(self):
        self.schedule.setAutomatic(True)
        self.assertEqual(self.schedule.runNow(self.job), "")
        self.wait_for(self.started["scheduled"].is_set)
        self.manual("News")
        self.assertFalse(self.backend.running)
        self.manual("Tokopedia")
        self.wait_for(self.started["manual"].is_set)
        self.assertEqual(self.schedule.activeSource, "News")
        self.backend.stopScrape()
        self.assertTrue(self.tokens["manual"].is_set())
        self.assertFalse(self.tokens["scheduled"].is_set())
        self.schedule.setAutomatic(False)
        for event in self.release.values():
            event.set()
        self.wait_for(lambda: not self.backend.running and not self.schedule.activeId)
        self.assertEqual(self.backend.rows[0]["title"], "manual")
        self.assertEqual(storage.list_crawl_runs()[0]["status"], "done")
        for source, keyword in (("Tokopedia", "manual"), ("News", "scheduled")):
            self.assertTrue(storage.get_cached_rows(source, keyword)[1])

    def test_due_job_skips_manual_source_then_resumes_it(self):
        self.schedule.setAutomatic(True)
        self.manual("Tokopedia")
        self.wait_for(self.started["manual"].is_set)
        same = storage.add_scheduled_job("Tokopedia", "same", next_run_at="1999-01-01T00:00:00")
        self.assertTrue(self.schedule.runNow(same))
        self.make_due(self.job)
        self.wait_for(self.started["scheduled"].is_set)
        self.assertEqual(self.schedule.activeId, self.job)
        self.release["scheduled"].set()
        self.wait_for(lambda: not self.schedule.activeId)
        self.assertIsNone(storage.get_scheduled_job(same)["last_run_at"])
        self.started["same"] = threading.Event()
        self.release["same"] = threading.Event()
        self.release["same"].set()
        self.release["manual"].set()
        self.wait_for(lambda: storage.get_scheduled_job(same)["last_status"] == "done")
