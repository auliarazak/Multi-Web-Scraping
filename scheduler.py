# scheduler.py
"""
Penjadwal otomatis untuk market_scraper_gui.

Prinsip:
- Job dibuat user dari GUI, disimpan di tabel scheduled_jobs (storage.py).
  Tidak ada keyword/source yang di-hardcode di sini.
- Scheduler hanya berjalan selama aplikasi dibuka (aplikasi desktop).
  Thread ini daemon, jadi ikut berhenti saat aplikasi ditutup.
- Job dieksekusi satu per satu (antri), bukan paralel, supaya tidak
  bentrok dengan scrape manual dan tidak membanjiri situs tujuan.
- Kalau aplikasi sedang sibuk scrape manual, job yang jatuh tempo
  dilewati dulu pada tick itu dan dicoba lagi pada tick berikutnya,
  karena next_run_at-nya belum digeser sampai job benar-benar jalan.
- Kalau aplikasi lama tertutup dan job tertinggal, saat dibuka lagi
  job itu jalan sekali, lalu next_run digeser ke sekarang + interval
  (tidak menumpuk eksekusi tertinggal). Logika geser next_run ada
  di storage.finish_scheduled_job.
"""

import datetime as dt
import threading

from storage import get_due_jobs, finish_scheduled_job


class JobScheduler(threading.Thread):
    def __init__(self, run_job, is_busy=None, check_interval_sec=60,
                 on_jobs_changed=None):
        """
        run_job(job_dict) -> (rows_found:int, error:str)
            Fungsi yang disediakan aplikasi: menjalankan scraper untuk
            satu job, menyimpan hasilnya ke DB, dan mengembalikan
            jumlah baris. Kalau gagal, raise atau return error.
        is_busy() -> bool
            Opsional: True kalau aplikasi sedang scrape manual, supaya
            scheduler menunggu giliran.
        on_jobs_changed()
            Opsional: dipanggil (dari thread scheduler) setelah ada job
            yang selesai; aplikasi boleh meneruskannya ke GUI lewat
            master.after() karena Tkinter tidak aman dipanggil dari
            thread lain secara langsung.
        """
        super().__init__(daemon=True)
        self.run_job = run_job
        self.is_busy = is_busy
        self.check_interval_sec = check_interval_sec
        self.on_jobs_changed = on_jobs_changed
        self._stop = threading.Event()
        self.current_job_id = None

    def stop(self):
        self._stop.set()

    def run_once(self):
        """Satu tick: jalankan semua job yang jatuh tempo, secara antri."""
        if self.is_busy and self.is_busy():
            return []
        finished = []
        for job in get_due_jobs():
            if self._stop.is_set():
                break
            if self.is_busy and self.is_busy():
                break
            self.current_job_id = job["id"]
            started = dt.datetime.now().isoformat(timespec="seconds")
            try:
                rows_found, error = self.run_job(job)
                status = "done" if not error else "failed"
                rows_found = int(rows_found or 0)
            except Exception as e:  # noqa: BLE001 - dicatat ke crawl_runs
                rows_found, error, status = 0, str(e), "failed"
            finally:
                self.current_job_id = None
            finish_scheduled_job(
                job["id"], status, rows_found=rows_found,
                error=error or "", started_at=started,
            )
            finished.append(job["id"])
        if finished and self.on_jobs_changed:
            try:
                self.on_jobs_changed()
            except Exception:
                pass
        return finished

    def run(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # Scheduler tidak boleh mati karena satu tick gagal;
                # kegagalan per job sudah dicatat di crawl_runs.
                pass
            self._stop.wait(self.check_interval_sec)
