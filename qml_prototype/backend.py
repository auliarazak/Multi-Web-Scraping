import os
import tempfile
import threading

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot

from config import (
    DEFAULT_LIMIT, SCROLL_ROUNDS, SCROLL_WAIT,
    DEFAULT_REVIEW_LOCATION,
)
from scraper.shopee import scrape_shopee
from scraper.tokopedia import scrape_tokopedia
from scraper.lazada import scrape_lazada
from scraper.news import scrape_news_indonesia
from scraper.google_reviews import scrape_google_reviews_by_name
from scraper.google_research import scrape_google_research, suggest_keywords
from storage import (
    suggest_history, reviews_cache_keyword,
)
from scrape_pipeline import run_pipeline
from exporters import export_csv, export_json
from .schedule import ScheduleController
from .result_table import SCHEMAS, columns_for, visible_rows

MARKETS = ("Shopee", "Tokopedia", "Lazada", "Google Reviews", "News",
           "Google Research")

EXTRA_EXPORT_FIELDS = {
    "Shopee": ("review_count", "sold", "shop_name"),
    "Tokopedia": ("shop_name",),
}


def _pick(d, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def _safe_url(x):
    return ("" if x is None else str(x)).strip().lower()


def _normalize_row(market, keyword, r):
    return {
        "source": _pick(r, "source", default=market),
        "keyword": keyword,
        "title": _pick(r, "title"),
        "url": _pick(r, "url"),
        "rating": _pick(r, "rating"),
        "comment": _pick(r, "comment"),
        "scraped_at": _pick(r, "scraped_at"),
      
        "harga": _pick(r, "harga", "price", "price_text"),
        "price_text": _pick(r, "price_text", "harga", "price"),
        "price_num": _pick(r, "price_num"),
        "sold_text": _pick(r, "sold_text"),
        "sold_num": _pick(r, "sold_num"),
        "sold": _pick(r, "sold", "sold_text"),
        "shop_name": _pick(r, "shop_name", "toko"),
        "location": _pick(r, "location"),
        "image": _pick(r, "image"),

        "category": _pick(r, "category"),
        "price_range": _pick(r, "price_range"),
        "review_count": _pick(r, "review_count"),
        "address": _pick(r, "address"),
        "country": _pick(r, "country"),
        "city": _pick(r, "city"),

        "authors": _pick(r, "authors"),
        "year": _pick(r, "year"),
        "abstract": _pick(r, "abstract"),

        "published": _pick(r, "published", "Price/Star"),
    }


def _display_row(market, keyword, r):
    row = _normalize_row(market, keyword, r)
    row["market"] = market
    row["title"] = row["title"] or "(tanpa judul)"
    if market == "Google Reviews" and "||" in keyword:
        row["search_key"] = keyword
        row["keyword"] = keyword.partition("||")[0]
    return row


def _storage_row(n):
    return {
        "source": n["source"], "keyword": n["keyword"],
        "title": n["title"], "url": n["url"],
        "harga": n["harga"], "rating": n["rating"], "comment": n["comment"],
        "authors": n["authors"], "year": n["year"], "abstract": n["abstract"],
        "category": n["category"], "price_range": n["price_range"],
        "review_count": n["review_count"],
        "address": n["address"], "country": n["country"], "city": n["city"],
        "published": n["published"], "scraped_at": n["scraped_at"],
        "price_text": n["price_text"], "price_num": n["price_num"],
        "sold_text": n["sold_text"], "sold_num": n["sold_num"],
        "sold": n["sold"], "shop_name": n["shop_name"],
        "location": n["location"], "image": n["image"],
    }


class Backend(QObject):

    rowsChanged = Signal()
    viewChanged = Signal()
    orderChanged = Signal()
    statusChanged = Signal()
    runningChanged = Signal()
    canScrapeChanged = Signal()
    sourceChanged = Signal()
    suggestionsChanged = Signal()
    _resultsReady = Signal(list, str)
    _progressReady = Signal(list, int, int, int)
    _partialReady = Signal(str, int)

    def __init__(self):
        super().__init__()
        self._rows = []
        self._previous_results = {}
        self._filter = ""
        self._sort_key = ""
        self._descending = False
        self.rowsChanged.connect(self.viewChanged.emit)
        self._status = "Siap. Pilih source di kiri, isi keyword, klik Scrape."
        self._running = False
        self._source = MARKETS[0]
        self._partial_note = ""
        self._last_limit = DEFAULT_LIMIT
        self._stop_event = threading.Event()
        self._stopped = False
        self._suggestions = None  
        self._suggestions_version = 0  
        self._resultsReady.connect(self._on_results)
        self._progressReady.connect(self._on_progress)
        self._partialReady.connect(self._on_partial)
        self._schedule = ScheduleController(
            MARKETS, self._run_scheduled_scrape, lambda: self.manualSource, parent=self)
        self._schedule.activeChanged.connect(self._schedule_activity_changed)

    @Property(list, notify=rowsChanged)
    def rows(self):
        return self._rows

    @Property(list, notify=sourceChanged)
    def columns(self):
        return columns_for(self._source)

    @Property(list, notify=viewChanged)
    def visibleRows(self):
        return visible_rows(self._rows, self._source, self._filter, self._sort_key, self._descending)

    @Property(str, notify=orderChanged)
    def sortKey(self):
        return self._sort_key

    @Property(bool, notify=orderChanged)
    def sortDescending(self):
        return self._descending

    @Slot(str)
    def setFilter(self, text):
        if text != self._filter:
            self._filter = text
            self.viewChanged.emit()

    @Slot(str)
    def sortBy(self, key):
        if key in SCHEMAS[self._source]:
            self._descending = not self._descending if key == self._sort_key else False
            self._sort_key = key
            self.orderChanged.emit()
            self.viewChanged.emit()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status

    @Property(bool, notify=runningChanged)
    def running(self):
        return self._running

    @Property(str, notify=runningChanged)
    def manualSource(self):
        return self._source if self._running else ""

    @Property(bool, notify=canScrapeChanged)
    def canScrape(self):
        return not self._running and self._schedule.activeSource != self._source

    @Property(QObject, constant=True)
    def schedule(self):
        return self._schedule

    @Property(str, notify=sourceChanged)
    def currentSource(self):
        return self._source

    @Property(list, constant=True)
    def sources(self):
        return list(MARKETS)

    @Property(int, notify=suggestionsChanged)
    def suggestionsVersion(self):
        return self._suggestions_version

    @Slot(str)
    def setSource(self, source):
        if not self._running and source in MARKETS and source != self._source:
            self._previous_results[self._source] = self._rows, self._status
            self._source = source
            self._rows, status = self._previous_results.get(source, ([], f"Siap. Sumber: {source}"))
            self._filter, self._sort_key, self._descending = "", "", False
            self.sourceChanged.emit()
            self.rowsChanged.emit()
            self.orderChanged.emit()
            self._set_status(status)
            self.canScrapeChanged.emit()

    @Slot(str, str, int, bool, bool, str)
    def scrape(self, keyword, mode, limit, force_refresh,
               headless, location):
        keyword = (keyword or "").strip()
        if not keyword:
            self._set_status("Masukkan keyword / URL dulu.")
            return
        if not self.canScrape:
            return
        if mode == "url" and self._source == "Google Reviews":
            self._set_status("Google Reviews tidak mendukung mode URL.")
            return
        self._set_running(True)
        self._stop_event.clear()
        self._stopped = False
        self._last_limit = int(limit or DEFAULT_LIMIT)
        self._set_status(f"Scraping {self._source}… (database dicek dulu)")
        source = self._source
        location = (location or "").strip() or DEFAULT_REVIEW_LOCATION
        worker = threading.Thread(
            target=self._worker, daemon=True,
            args=(source, mode, keyword, int(limit or DEFAULT_LIMIT),
                  bool(force_refresh), bool(headless), location),
        )
        try:
            worker.start()
        except RuntimeError as exc:
            self._set_running(False)
            self._set_status(f"Gagal memulai scrape: {exc}")

    @Slot()
    def stopScrape(self):
        self._stop_event.set()

    @Slot(QUrl, str, "QVariantList", result=str)
    def exportRows(self, destination, fmt, rows):
        writers = {"csv": export_csv, "json": export_json}
        if fmt not in writers or not destination.isLocalFile():
            return "Pilih file CSV atau JSON di komputer ini."
        if not rows:
            return "Tidak ada hasil yang tampil untuk diekspor."

        path = destination.toLocalFile()
        if not path.lower().endswith(f".{fmt}"):
            return f"Gagal mengekspor: nama file harus berakhiran .{fmt}."
        temp_path = None
        try:
            records = []
            for row in rows:
                market = row["market"]
                fields = (*SCHEMAS[market][:-1], *EXTRA_EXPORT_FIELDS.get(market, ()), "url", "scraped_at")
                record = {field: row.get(field, "") for field in fields}
                record["keyword"] = row.get("search_key", record["keyword"])
                if fmt == "csv":
                    for field, value in record.items():
                        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                            record[field] = "'" + value
                records.append(record)
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=f".{fmt}")
            os.close(fd)
            writers[fmt](temp_path, records)
            os.replace(temp_path, path)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return f"Gagal mengekspor: {exc}"
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return f"{len(rows)} baris disimpan ke {os.path.basename(path)}."

    @Slot()
    def shutdown(self):
        self._stop_event.set()
        self._schedule.stop()

    @Slot(result="QVariant")
    def keywordSuggestions(self):
        if self._suggestions is None:
            try:
                self._suggestions = suggest_keywords()
            except Exception:
                self._suggestions = {"words": [], "pairs": []}
        return self._suggestions

    @Slot(str, result="QVariant")
    def suggestionsFor(self, source):
        try:
            if source == "Google Research":
                return self.keywordSuggestions()
            if source == "Shopee":
                return {"words": [], "pairs": []}
            return {"words": suggest_history(source), "pairs": []}
        except Exception:
            return {"words": [], "pairs": []}

    def _set_status(self, text):
        self._status = text
        self.statusChanged.emit()

    def _set_running(self, value):
        self._running = value
        self.runningChanged.emit()
        self.canScrapeChanged.emit()

    @Slot()
    def _schedule_activity_changed(self):
        self.canScrapeChanged.emit()
        if not self._schedule.activeId:
            self._refresh_suggestions()

    def _refresh_suggestions(self):
        self._suggestions_version += 1
        self.suggestionsChanged.emit()

    def _worker(self, market, mode, keyword, limit, force_refresh,
                headless, location):
        try:
            rows, data_source = self._pipeline(
                market, mode, keyword, limit, force_refresh,
                headless, location)
            self._resultsReady.emit(rows, data_source)
        except Exception as exc:
            self._resultsReady.emit([], f"error:{exc}")

    def _on_progress(self, rows, found, limit, round_no):

        self._rows = rows
        self.rowsChanged.emit()
        self._set_status(
            f"Mengumpulkan {found}/{limit}… • ronde {round_no} • "
            f"Source: {self._source}")

    def _on_partial(self, error, found):
        self._partial_note = f"parsial ({found} baris) — {error}"

    def _on_results(self, rows, data_source):
        self._set_running(False)
        QTimer.singleShot(0, self._schedule.check_due_jobs)
        self._refresh_suggestions()
        if isinstance(data_source, str) and data_source.startswith("error:"):
            self._rows = []
            self.rowsChanged.emit()
            self._set_status(f"Gagal: {data_source[6:]}")
            self._partial_note = ""
            return
        self._rows = rows
        self.rowsChanged.emit()
        label = ("database (cache)" if data_source == "database"
                 else "web")
        if self._stopped:
            self._stopped = False
            self._partial_note = ""
            self._set_status(
                f"Dihentikan: {len(rows)} baris (parsial) dari "
                f"{label} • Source: {self._source}")
            return
        if self._partial_note:
            status = (
                f"Selesai {self._partial_note}: {len(rows)} baris "
                f"dari {label} • Source: {self._source}")
            self._partial_note = ""
        else:
            status = (
                f"Selesai: {len(rows)} baris dari {label} • Source: "
                f"{self._source}")
        if len(rows) < self._last_limit:
            if data_source == "database":
                status += (
                    f" • ⚠ Hanya {len(rows)}/{self._last_limit} dari "
                    "cache — Paksa refresh untuk scrape ulang ke web")
            else:
                status += (
                    f" • ⚠ Hanya {len(rows)}/{self._last_limit} — "
                    "scrape berhenti, feed tidak bertambah lagi "
                    "(coba Paksa refresh untuk mencoba lagi)")
        self._set_status(status)

    def _pipeline(self, market, mode, keyword, limit, force_refresh,
                  headless, location):
        cache_keyword = (reviews_cache_keyword(keyword, location)
                         if market == "Google Reviews" and mode == "keyword"
                         else keyword)

        def progress(found, limit_, round_no, snapshot=None):
            if snapshot is not None:
                rows = [_display_row(market, cache_keyword, r) for r in snapshot]
                self._progressReady.emit(rows, int(found), int(limit_), int(round_no))

        def partial(error, found):
            self._partialReady.emit(str(error), int(found))

        def scrape():
            raw = self._scrape_from_web(
                market, mode, keyword, limit, headless, location,
                on_progress=progress, on_partial=partial)
            self._stopped = self._stop_event.is_set()
            return raw

        return run_pipeline(market, mode, keyword, limit, force_refresh,
                            location, scrape, _normalize_row, _display_row,
                            _storage_row)

    def _run_scheduled_scrape(self, job, stop_event):
        market, mode, keyword = job["source"], job["mode"], job["keyword"]
        location = job["location"] or DEFAULT_REVIEW_LOCATION
        limit = job["limit_rows"]
        problems = []

        def fetch():
            return self._scrape_from_web(
                market, mode, keyword, limit, bool(job["headless"]), location,
                on_partial=lambda error, _found: problems.append(str(error)),
                stop_event=stop_event)

        rows, _ = run_pipeline(market, mode, keyword, limit, True, location,
                               fetch, _normalize_row, _display_row, _storage_row)
        return sum(bool(row["url"]) for row in rows), "; ".join(problems)

    def _scrape_from_web(self, market, mode, keyword, limit,
                         headless, location, on_progress=None,
                         on_partial=None, stop_event=None):
        if stop_event is None:
            stop_event = self._stop_event
        kw = keyword if mode == "keyword" else None
        url = keyword if mode == "url" else None
        if market == "Shopee":
            return scrape_shopee(keyword=kw, url=url, headless=headless,
                                 limit=limit, scroll_rounds=SCROLL_ROUNDS,
                                 wait=SCROLL_WAIT)
        if market == "Tokopedia":
            return scrape_tokopedia(keyword=kw, url=url, headless=headless,
                                    limit=limit, scroll_rounds=SCROLL_ROUNDS,
                                    wait=SCROLL_WAIT,
                                    on_progress=on_progress,
                                    on_partial=on_partial,
                                    stop_event=stop_event)
        if market == "Lazada":
            return scrape_lazada(keyword=kw, url=url, headless=headless,
                                 limit=limit, scroll_rounds=SCROLL_ROUNDS,
                                 wait=SCROLL_WAIT,
                                 stop_event=stop_event)
        if market == "Google Reviews":
            return scrape_google_reviews_by_name(
                place_name=keyword, headless=headless, limit=limit,
                scroll_rounds=SCROLL_ROUNDS, wait=SCROLL_WAIT,
                location=(location or "").strip(),
                stop_event=stop_event)
        if market == "Google Research":
            return scrape_google_research(keyword=kw, url=url,
                                          limit=limit, wait=0.2,
                                          stop_event=stop_event)
        if market == "News":
            return scrape_news_indonesia(keyword=kw, url=url, limit=limit)
        raise ValueError("Source tidak dikenali")