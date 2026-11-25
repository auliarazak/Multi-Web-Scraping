import datetime as dt
import math
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

import storage


class ScheduleController(QObject):
    changed = Signal()
    activeChanged = Signal()
    automaticChanged = Signal()
    jobSaved = Signal(int)
    _finished = Signal(str)

    def __init__(self, sources, scrape_job, manual_source, parent=None):
        super().__init__(parent)
        self._sources = tuple(s for s in sources if s != "Shopee")
        self._scrape_job = scrape_job
        self._manual_source = manual_source
        self._automatic = False
        self._active_id = 0
        self._active_source = ""
        self._notice = ""
        self._stop_event = threading.Event()
        self._finished.connect(self._on_finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check_due_jobs)

    @Property(bool, notify=automaticChanged)
    def automaticEnabled(self):
        return self._automatic

    @Slot(bool, result=str)
    def setAutomatic(self, enabled):
        if self._automatic == enabled or self._stop_event.is_set():
            return ""
        if enabled:
            try:
                storage.start_schedule_intervals(self._sources)
            except Exception as exc:
                return f"Gagal menyalakan jadwal: {exc}"
        self._automatic = enabled
        self._timer.stop()
        self._notice = ""
        self.automaticChanged.emit()
        self._jobs_changed()
        return ""

    def _jobs_changed(self):
        self.changed.emit()
        if self._automatic:
            self._timer.start(0)

    @Property(list, constant=True)
    def sources(self):
        return list(self._sources)

    @Property(int, notify=activeChanged)
    def activeId(self):
        return self._active_id

    @Property(str, notify=activeChanged)
    def activeSource(self):
        return self._active_source

    @Slot(result="QVariantMap")
    def snapshot(self):
        try:
            return {"jobs": storage.list_scheduled_jobs(),
                    "runs": storage.list_crawl_runs(), "error": self._notice}
        except Exception as exc:
            return {"jobs": [], "runs": [], "error": f"Gagal membaca jadwal: {exc}"}

    @Slot(int, str, str, str, int, int, str, result=str)
    @Slot(int, str, str, str, int, int, str, bool, result=str)
    def saveJob(self, job_id, source, mode, keyword, limit, interval, location, headless=None):
        keyword = keyword.strip()
        if source not in self._sources or mode not in ("keyword", "url"):
            return "Pilih sumber dan mode yang valid."
        if not keyword:
            return "Masukkan keyword atau URL."
        if mode == "url":
            if source == "Google Reviews":
                return "Google Reviews hanya mendukung mode keyword."
            try:
                parsed = urlsplit(keyword)
                valid_url = parsed.scheme in ("http", "https") and parsed.hostname
            except ValueError:
                valid_url = False
            if not valid_url:
                return "Masukkan URL lengkap yang diawali http:// atau https://."
        if not 1 <= limit <= 500 or not 1 <= interval <= 525_600:
            return "Limit harus 1–500 dan interval harus 1 menit hingga 365 hari."

        fields = dict(source=source, keyword=keyword, mode=mode, limit_rows=limit,
                      interval_minutes=interval,
                      headless=int(source != "Tokopedia" if headless is None else headless),
                      location=location.strip() if source == "Google Reviews" else "")
        try:
            if job_id:
                if not self._editable_job(job_id):
                    return "Jadwal sedang berjalan atau sudah dihapus."
                next_run = dt.datetime.now() + dt.timedelta(minutes=interval)
                storage.update_scheduled_job(
                    job_id, **fields, next_run_at=next_run.isoformat(timespec="seconds"))
            else:
                job_id = storage.add_scheduled_job(**fields)
        except Exception as exc:
            return f"Gagal menyimpan jadwal: {exc}"
        self._jobs_changed()
        self.jobSaved.emit(job_id)
        return ""

    def _editable_job(self, job_id):
        return job_id > 0 and job_id != self._active_id and storage.get_scheduled_job(job_id)

    @Slot(int, bool, result=str)
    def setJobActive(self, job_id, active):
        try:
            job = self._editable_job(job_id)
            if not job:
                return "Jadwal sedang berjalan atau sudah dihapus."
            if active:
                next_run = dt.datetime.now() + dt.timedelta(minutes=job["interval_minutes"])
                storage.update_scheduled_job(job_id, active=1, next_run_at=next_run.isoformat(timespec="seconds"))
            else:
                storage.set_job_active(job_id, False)
        except Exception as exc:
            return f"Gagal mengubah status jadwal: {exc}"
        self._jobs_changed()
        return ""

    @Slot(int, result=str)
    def deleteJob(self, job_id):
        try:
            if not self._editable_job(job_id):
                return "Jadwal sedang berjalan atau sudah dihapus."
            storage.delete_scheduled_job(job_id)
        except Exception as exc:
            return f"Gagal menghapus jadwal: {exc}"
        self._jobs_changed()
        return ""

    @Slot(int, result=str)
    def runNow(self, job_id):
        if not self._automatic or self._stop_event.is_set():
            return "Nyalakan jadwal otomatis terlebih dahulu."
        if self._active_id:
            return "Tugas terjadwal lain sedang berjalan."
        try:
            job = storage.get_scheduled_job(job_id)
            if not job or job["source"] not in self._sources:
                return "Jadwal ini tidak tersedia untuk dijalankan."
            if job["source"] == self._manual_source():
                return f"Scrape manual {job['source']} sedang berjalan."
            self._start(job)
        except Exception as exc:
            return f"Gagal memulai jadwal: {exc}"
        return ""

    @Slot()
    def check_due_jobs(self):
        if not self._automatic or self._active_id or self._stop_event.is_set():
            return
        try:
            manual = self._manual_source()
            job = next((j for j in storage.list_scheduled_jobs(active_only=True)
                        if j["source"] in self._sources and j["source"] != manual), None)
            if job:
                due = job["next_run_at"]
                if due:
                    delay = (dt.datetime.fromisoformat(due) - dt.datetime.now()).total_seconds()
                    if delay > 0:
                        self._timer.start(min(60_000, math.ceil(delay * 1000)))
                        return
                self._start(job)
        except Exception as exc:
            self._notice = f"Gagal memeriksa jadwal: {exc}"
            self.changed.emit()
            self._timer.start(60_000)

    def _start(self, job):
        worker = threading.Thread(target=self._worker, args=(job,), daemon=True)
        self._active_id = job["id"]
        self._active_source = job["source"]
        self._notice = ""
        try:
            worker.start()
        except Exception:
            self._active_id = 0
            self._active_source = ""
            raise
        self.activeChanged.emit()
        self.changed.emit()

    def _worker(self, job):
        started = dt.datetime.now().isoformat(timespec="seconds")
        try:
            rows, problem = self._scrape_job(job, self._stop_event)
            status = "partial" if problem else "done" if rows else "empty"
        except Exception as exc:
            rows, problem, status = 0, str(exc) or type(exc).__name__, "failed"
        if self._stop_event.is_set():
            return
        try:
            storage.finish_scheduled_job(job["id"], status, rows_found=rows,
                                         error=problem, started_at=started)
        except Exception as exc:
            self._finished.emit(f"Gagal mencatat hasil jadwal: {exc}")
        else:
            self._finished.emit("")

    @Slot(str)
    def _on_finished(self, notice):
        self._active_id = 0
        self._active_source = ""
        self._notice = notice
        self.activeChanged.emit()
        self.changed.emit()
        if self._automatic and not self._stop_event.is_set():
            self._timer.start(60_000 if notice else 0)

    def stop(self):
        self._stop_event.set()
        self._timer.stop()