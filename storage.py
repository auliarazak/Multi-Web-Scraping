import sqlite3
import datetime as dt
from contextlib import closing
from typing import List, Dict
from config import DB_PATH


CREATE_ITEMS = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    keyword TEXT,
    title TEXT,
    url TEXT UNIQUE,
    scraped_at TEXT
);
"""


CREATE_ECOMMERCE = """
CREATE TABLE IF NOT EXISTS ecommerce_detail (
    item_id INTEGER,
    harga TEXT,
    rating TEXT,
    review_count TEXT,
    sold TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);
"""


CREATE_RESEARCH = """
CREATE TABLE IF NOT EXISTS research_detail (
    item_id INTEGER,
    authors TEXT,
    year TEXT,
    abstract TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);
"""


CREATE_REVIEW = """
CREATE TABLE IF NOT EXISTS review_detail (
    item_id INTEGER,
    category TEXT,
    price_range TEXT,
    review_count TEXT,
    rating TEXT,
    address TEXT,
    country TEXT,
    city TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);
"""


CREATE_NEWS = """
CREATE TABLE IF NOT EXISTS news_detail (
    item_id INTEGER,
    published TEXT,
    comment TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);
"""

CREATE_KEYWORD_CACHE = """
CREATE TABLE IF NOT EXISTS keyword_cache (
    source TEXT NOT NULL,
    keyword TEXT NOT NULL,
    keyword_norm TEXT NOT NULL,
    last_scraped_at TEXT,
    ttl_hours INTEGER NOT NULL DEFAULT 24,
    row_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(source, keyword_norm)
);
"""


CREATE_SCHEDULED_JOBS = """
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    keyword TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'keyword',
    limit_rows INTEGER NOT NULL DEFAULT 60,
    interval_minutes INTEGER NOT NULL DEFAULT 1440,
    next_run_at TEXT,
    last_run_at TEXT,
    last_status TEXT,
    last_rows INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT
);
"""


CREATE_CRAWL_RUNS = """
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    source TEXT,
    keyword TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    rows_found INTEGER,
    error TEXT,
    FOREIGN KEY(job_id) REFERENCES scheduled_jobs(id)
);
"""

CREATE_SEARCH_RESULTS = """
CREATE TABLE IF NOT EXISTS search_results (
    source TEXT NOT NULL,
    keyword_norm TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES items(id),
    found_at TEXT NOT NULL,
    PRIMARY KEY (source, keyword_norm, item_id)
);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(CREATE_ITEMS)
    cur.execute(CREATE_ECOMMERCE)
    cur.execute(CREATE_RESEARCH)
    cur.execute(CREATE_REVIEW)
    cur.execute(CREATE_NEWS)


    cur.execute(CREATE_KEYWORD_CACHE)
    cur.execute(CREATE_SCHEDULED_JOBS)
    cur.execute(CREATE_CRAWL_RUNS)
    cur.execute(CREATE_SEARCH_RESULTS)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_source_keyword_scraped "
        "ON items(source, keyword, scraped_at)"
    )


    cur.execute("BEGIN IMMEDIATE")
    version = cur.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        cur.execute(
            "UPDATE items SET scraped_at = '2000-01-01' "
            "WHERE source = 'Google Reviews'"
        )
        cur.execute("DELETE FROM keyword_cache WHERE source = 'Google Reviews'")
        cur.execute("PRAGMA user_version = 1")

    if version < 2:

        for item_id, source, keyword, scraped_at in cur.execute(
            "SELECT id, source, keyword, scraped_at FROM items"
        ).fetchall():
            if source and keyword and scraped_at:
                cache_source = "News" if source.startswith("News - ") else source
                cur.execute(
                    "INSERT OR IGNORE INTO search_results VALUES (?, ?, ?, ?)",
                    (cache_source, normalize_keyword(keyword), item_id, scraped_at),
                )
        cur.execute("PRAGMA user_version = 2")

    if version < 3:
        for table, column in (("scheduled_jobs", "location"),
                              ("ecommerce_detail", "shop_name")):
            columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        cur.execute("PRAGMA user_version = 3")

    if version < 4:
        columns = {row[1] for row in cur.execute("PRAGMA table_info(scheduled_jobs)")}
        if "headless" not in columns:
            cur.execute("ALTER TABLE scheduled_jobs ADD COLUMN headless INTEGER NOT NULL DEFAULT 1")
            cur.execute("UPDATE scheduled_jobs SET headless = 0 WHERE source = 'Tokopedia'")
        cur.execute("PRAGMA user_version = 4")

    conn.commit()
    conn.close()


def _safe_str(x):
    return "" if x is None else str(x)


def _get_existing_item_id(cur, url: str):
    if not url:
        return None

    cur.execute("SELECT id FROM items WHERE url = ?", (url,))
    row = cur.fetchone()
    return row[0] if row else None


def _insert_or_get_item_id(cur, r: Dict, now: str):
    url = _safe_str(r.get("url")).strip()
    if not url:
        return None

    existing_id = _get_existing_item_id(cur, url)
    if existing_id:
        new_kw = _safe_str(r.get("keyword"))
        cur.execute("SELECT keyword FROM items WHERE id = ?", (existing_id,))
        old_row = cur.fetchone()
        old_kw = _safe_str(old_row[0]) if old_row else ""
        if (new_kw != old_kw and "||" not in old_kw
                and _base_keyword(new_kw) == _base_keyword(old_kw)):
            cur.execute(
                "UPDATE items SET scraped_at = ?, title = ?, keyword = ? "
                "WHERE id = ?",
                (now, _safe_str(r.get("title")), new_kw, existing_id),
            )
        else:
            cur.execute(
                "UPDATE items SET scraped_at = ?, title = ? WHERE id = ?",
                (now, _safe_str(r.get("title")), existing_id),
            )
        return existing_id

    cur.execute(
        """
        INSERT INTO items
        (source, keyword, title, url, scraped_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            _safe_str(r.get("source")),
            _safe_str(r.get("keyword")),
            _safe_str(r.get("title")),
            url,
            _safe_str(r.get("scraped_at")) or now,
        ),
    )

    return cur.lastrowid



def save_rows_to_db(rows: List[Dict]):

    if not rows:
        return 0

    inserted = 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        with closing(sqlite3.connect(DB_PATH, timeout=15)) as conn, conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            for r in rows:
                item_id = _insert_or_get_item_id(cur, r, now)

                if not item_id:
                    continue

                source = (_safe_str(r.get("source"))).lower()

                if source in ["shopee", "tokopedia", "lazada"]:
                    cur.execute("DELETE FROM ecommerce_detail WHERE item_id = ?", (item_id,))

                    cur.execute(
                        """
                        INSERT INTO ecommerce_detail
                        (item_id, harga, rating, review_count, sold, shop_name)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            _safe_str(r.get("harga")),
                            _safe_str(r.get("rating")),
                            _safe_str(r.get("review_count")),
                            _safe_str(r.get("sold")),
                            _safe_str(r.get("shop_name")),
                        ),
                    )

                elif "research" in source:
                    cur.execute("DELETE FROM research_detail WHERE item_id = ?", (item_id,))

                    cur.execute(
                        """
                        INSERT INTO research_detail
                        (item_id, authors, year, abstract)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            _safe_str(r.get("authors")),
                            _safe_str(r.get("year")),
                            _safe_str(r.get("abstract")),
                        ),
                    )

                elif "review" in source:
                    cur.execute("DELETE FROM review_detail WHERE item_id = ?", (item_id,))

                    cur.execute(
                        """
                        INSERT INTO review_detail
                        (item_id, category, price_range, review_count, rating,
                         address, country, city)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            _safe_str(r.get("category")),
                            _safe_str(r.get("price_range")),
                            _safe_str(r.get("review_count")),
                            _safe_str(r.get("rating")),
                            _safe_str(r.get("address")),
                            _safe_str(r.get("country")),
                            _safe_str(r.get("city")),
                        ),
                    )

                elif "news" in source:
                    cur.execute("DELETE FROM news_detail WHERE item_id = ?", (item_id,))

                    cur.execute(
                        """
                        INSERT INTO news_detail
                        (item_id, published, comment)
                        VALUES (?, ?, ?)
                        """,
                        (
                            item_id,
                            _safe_str(r.get("published")),
                            _safe_str(r.get("comment")),
                        ),
                    )

                cache_source = _safe_str(r.get("source"))
                if cache_source.startswith("News - "):
                    cache_source = "News"
                cur.execute(
                    "INSERT INTO search_results(source, keyword_norm, item_id, found_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(source, keyword_norm, item_id) "
                    "DO UPDATE SET found_at = excluded.found_at",
                    (cache_source, normalize_keyword(r.get("keyword")), item_id, now),
                )
                inserted += 1
    except Exception as exc:
        raise RuntimeError(f"Gagal menyimpan hasil ke database: {exc}") from exc

    return inserted


import re as _re


def normalize_keyword(keyword: str) -> str:
    return _re.sub(r"\s+", " ", _safe_str(keyword).strip().lower())


def reviews_cache_keyword(keyword: str, location: str = "") -> str:
    loc = _safe_str(location).strip()
    if not loc:
        return keyword
    return f"{keyword}||{loc}"


def _base_keyword(keyword: str) -> str:

    return normalize_keyword(_safe_str(keyword).split("||")[0])


def default_ttl_hours(source: str) -> int:
    s = _safe_str(source).lower()
    if "news" in s:
        return 6
    if "research" in s:
        return 168 
    if "review" in s:
        return 72
    return 24 


def _parse_iso(text):
    try:
        return dt.datetime.fromisoformat(_safe_str(text))
    except Exception:
        return None


def _now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def update_cache(source: str, keyword: str, ttl_hours=None, row_count: int = 0):
    if ttl_hours is None:
        ttl_hours = default_ttl_hours(source)
    norm = normalize_keyword(keyword)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO keyword_cache
        (source, keyword, keyword_norm, last_scraped_at, ttl_hours, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, keyword_norm) DO UPDATE SET
            keyword = excluded.keyword,
            last_scraped_at = excluded.last_scraped_at,
            ttl_hours = excluded.ttl_hours,
            row_count = excluded.row_count
        """,
        (source, keyword, norm, _now_iso(), int(ttl_hours), int(row_count)),
    )
    conn.commit()
    conn.close()


def get_cache_info(source: str, keyword: str):
    norm = normalize_keyword(keyword)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM keyword_cache WHERE source = ? AND keyword_norm = ?",
        (source, norm),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    info = dict(row)
    last = _parse_iso(info.get("last_scraped_at"))
    ttl = int(info.get("ttl_hours") or default_ttl_hours(source))
    info["is_fresh"] = bool(
        last and (dt.datetime.now() - last) < dt.timedelta(hours=ttl)
    )
    return info


def suggest_history(source: str, limit: int = 10):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT keyword, row_count FROM keyword_cache "
        "WHERE source = ? AND row_count > 0 "
        "AND keyword NOT LIKE 'http%' AND keyword NOT LIKE '%://%' "
        "ORDER BY last_scraped_at DESC LIMIT ?",
        (source, int(limit)),
    )
    rows = []
    for r in cur.fetchall():
        kw = r["keyword"] or ""
        if "||" in kw:
            base, loc = kw.split("||", 1)
        else:
            base, loc = kw, ""
        rows.append({"keyword": base, "count": int(r["row_count"]),
                     "location": loc})
    conn.close()
    return rows


def _rows_from_items(cur, item_rows, source: str):
    out = []
    s = _safe_str(source).lower()
    for item in item_rows:
        item_id, src, kw, title, url, scraped_at = item
        r = {
            "source": src, "keyword": kw, "title": title, "url": url,
            "scraped_at": scraped_at,
        }
        if s in ("shopee", "tokopedia", "lazada"):
            d = cur.execute(
                "SELECT harga, rating, review_count, sold, shop_name "
                "FROM ecommerce_detail WHERE item_id = ? LIMIT 1",
                (item_id,),
            ).fetchone()
            if d:
                r.update({"harga": d[0], "rating": d[1],
                          "review_count": d[2], "sold": d[3], "shop_name": d[4]})
        elif "research" in s:
            d = cur.execute(
                "SELECT authors, year, abstract FROM research_detail "
                "WHERE item_id = ? LIMIT 1", (item_id,),
            ).fetchone()
            if d:
                r.update({"authors": d[0], "year": d[1], "abstract": d[2]})
        elif "review" in s:
            d = cur.execute(
                "SELECT category, price_range, review_count, rating, "
                "address, country, city FROM review_detail "
                "WHERE item_id = ? LIMIT 1", (item_id,),
            ).fetchone()
            if d:
                r.update({"category": d[0], "price_range": d[1],
                          "review_count": d[2], "rating": d[3],
                          "address": d[4], "country": d[5], "city": d[6]})
        elif "news" in s:
            d = cur.execute(
                "SELECT published, comment FROM news_detail "
                "WHERE item_id = ? LIMIT 1", (item_id,),
            ).fetchone()
            if d:
                r.update({"published": d[0], "comment": d[1]})
        out.append(r)
    return out


def get_cached_rows(source: str, keyword: str, ttl_hours=None):
    if ttl_hours is None:
        ttl_hours = default_ttl_hours(source)
    info = get_cache_info(source, keyword)
    if not info or not info["is_fresh"]:
        return [], False
    norm = normalize_keyword(keyword)
    cutoff = (dt.datetime.now() - dt.timedelta(hours=int(ttl_hours))).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT i.id, i.source, i.keyword, i.title, i.url, i.scraped_at "
        "FROM search_results s JOIN items i ON i.id = s.item_id "
        "WHERE s.source = ? AND s.keyword_norm = ? AND s.found_at >= ? "
        "ORDER BY i.id",
        (source, norm, cutoff),
    )
    rows = _rows_from_items(cur, cur.fetchall(), source)
    conn.close()
    if not rows:
        return [], False
    return rows, True


def get_cached_rows_by_url(url: str, ttl_hours: int = 24):
    url = _safe_str(url).strip()
    if not url:
        return [], False
    cutoff = (dt.datetime.now() - dt.timedelta(hours=int(ttl_hours))).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source, keyword, title, url, scraped_at FROM items "
        "WHERE url = ? AND scraped_at >= ?",
        (url, cutoff),
    )
    found = cur.fetchall()
    if not found:
        conn.close()
        return [], False
    rows = _rows_from_items(cur, found, found[0][1])
    conn.close()
    return rows, True



def start_schedule_intervals(sources):
    placeholders = ",".join("?" for _ in sources)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            "UPDATE scheduled_jobs SET next_run_at = "
            "strftime('%Y-%m-%dT%H:%M:%S', ?, '+' || interval_minutes || ' minutes') "
            f"WHERE active = 1 AND source IN ({placeholders})",
            (_now_iso(), *sources),
        )

def add_scheduled_job(source, keyword, mode="keyword", limit_rows=60,
                      interval_minutes=1440, next_run_at=None, location="", headless=None):
    now = dt.datetime.now()
    if not next_run_at:
        next_run_at = (now + dt.timedelta(minutes=int(interval_minutes))).isoformat(
            timespec="seconds"
        )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO scheduled_jobs
        (source, keyword, mode, limit_rows, interval_minutes,
         next_run_at, active, created_at, location, headless)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (source, keyword, mode, int(limit_rows), int(interval_minutes),
         next_run_at, now.isoformat(timespec="seconds"), location,
         int(source != "Tokopedia" if headless is None else headless)),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def list_scheduled_jobs(active_only=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sql = "SELECT * FROM scheduled_jobs"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY next_run_at"
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_scheduled_job(job_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_scheduled_job(job_id, **fields):
    allowed = {"source", "keyword", "mode", "limit_rows",
               "interval_minutes", "next_run_at", "active", "location", "headless"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return False
    vals.append(job_id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE scheduled_jobs SET {', '.join(sets)} WHERE id = ?", vals
    )
    conn.commit()
    conn.close()
    return True


def delete_scheduled_job(job_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def set_job_active(job_id: int, active: bool):
    return update_scheduled_job(job_id, active=1 if active else 0)


def get_due_jobs(now_iso=None):
    if not now_iso:
        now_iso = _now_iso()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM scheduled_jobs WHERE active = 1 "
        "AND (next_run_at IS NULL OR next_run_at <= ?) ORDER BY next_run_at",
        (now_iso,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def finish_scheduled_job(job_id, status, rows_found=0, error="",
                         started_at=None):
    now = dt.datetime.now()
    job = get_scheduled_job(job_id)
    interval = int(job["interval_minutes"]) if job else 1440
    next_run = (now + dt.timedelta(minutes=interval)).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE scheduled_jobs SET last_run_at = ?, last_status = ?,
            last_rows = ?, next_run_at = ? WHERE id = ?
        """,
        (now.isoformat(timespec="seconds"), status, int(rows_found),
         next_run, job_id),
    )
    cur.execute(
        """
        INSERT INTO crawl_runs
        (job_id, source, keyword, started_at, finished_at, status,
         rows_found, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, job["source"] if job else "", job["keyword"] if job else "",
         started_at or now.isoformat(timespec="seconds"),
         now.isoformat(timespec="seconds"), status, int(rows_found), error),
    )
    conn.commit()
    conn.close()
    return next_run


def list_crawl_runs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
