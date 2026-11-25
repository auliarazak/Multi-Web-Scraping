import datetime as dt
import feedparser
import re
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<.*?>", "", text)
    return text.replace("\n", " ").strip()


def _tokenize(s: str) -> list[str]:
    s = (s or "").lower()
    return [t for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 3]


def _match_keyword_relaxed(title: str, summary: str, keyword: str) -> bool:
    if not keyword:
        return True
    key_tokens = _tokenize(keyword)
    if not key_tokens:
        return True
    hay = set(_tokenize(f"{title} {summary}"))
    return any(t in hay for t in key_tokens)


def _entry_age_ok(e: dict, max_age_days: float) -> bool:
    parsed = e.get("published_parsed") or e.get("updated_parsed")
    if not parsed:
        return True
    try:
        pub = dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)
    except Exception:
        return True
    age = dt.datetime.now(dt.timezone.utc) - pub
    return age <= dt.timedelta(days=float(max_age_days))


def _requests_get(url: str, timeout: int = 15) -> requests.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def _is_feed_xml(text: str) -> bool:
    low = (text or "").lower()
    # heuristik ringan
    return ("<rss" in low) or ("<feed" in low) or ("<channel" in low and "<item" in low)


def _row_from_entry(source_label: str, e: dict, now: str) -> dict:
    title = e.get("title", "Tanpa Judul")
    link = (e.get("link", "") or "").strip()
    summary = clean_html(e.get("summary", "")) or ""
    published = e.get("published", "") or e.get("updated", "") or e.get("pubDate", "")
    return {
        "source": source_label,
        "title": title,
        "Price/Star": published,
        "comment": summary if summary else "(Ringkasan tidak tersedia)",
        "url": link,
        "scraped_at": now,
    }


def _detect_domain_key(url: str) -> str:
    netloc = (urlparse(url).netloc or "").lower()
    if "detik.com" in netloc:
        return "detik"
    if "kompas.com" in netloc:
        return "kompas"
    if "tempo.co" in netloc:
        return "tempo"
    if "cnnindonesia.com" in netloc:
        return "cnn"
    if "republika.co.id" in netloc:
        return "republika"
    if "antaranews.com" in netloc:
        return "antara"
    return "generic"


def _text_join(nodes) -> str:
    return " ".join(n.get_text(" ", strip=True) for n in nodes if n.get_text(strip=True))



def _parse_article_detik(soup: BeautifulSoup):
    # Detik: sering pakai detail__title dan detail__body-text
    title_el = soup.select_one("h1.detail__title") or soup.select_one("h1")
    body_nodes = soup.select("div.detail__body-text p")
    date_el = soup.select_one("div.detail__date") or soup.select_one("div.detail__date, span.detail__date")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes) or _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_kompas(soup: BeautifulSoup):
    title_el = soup.select_one("h1.read__title") or soup.select_one("h1")
    body_nodes = soup.select("div.read__content p") or soup.select("div.read__content")
    date_el = soup.select_one("div.read__time") or soup.select_one("div.read__time, div.read__time span")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes if isinstance(body_nodes, list) else [body_nodes]) if body_nodes else _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_tempo(soup: BeautifulSoup):
    title_el = soup.select_one("h1")
    body_nodes = soup.select("div.detail-konten p") or soup.select("div.detail__body p")
    date_el = soup.select_one("div.date") or soup.select_one("p.date") or soup.select_one("div.detail__date")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes) or _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_cnn(soup: BeautifulSoup):
    title_el = soup.select_one("h1")
    body_nodes = soup.select("div.detail-text p") or soup.select("div.detail-text")
    date_el = soup.select_one("div.text-cnn_black_light") or soup.select_one("div.detail__date")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes if isinstance(body_nodes, list) else [body_nodes]) if body_nodes else _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_republika(soup: BeautifulSoup):
    title_el = soup.select_one("h1")
    body_nodes = (
        soup.select("div.read__content p")
        or soup.select("div.detail_article p")
        or soup.select("div.article-content p")
    )
    date_el = soup.select_one("div.date") or soup.select_one("span.date") or soup.select_one("div.article__date")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes) or _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_antara(soup: BeautifulSoup):
    title_el = soup.select_one("h1") or soup.select_one("h1.post-title")
    body_nodes = soup.select("div.post-content p") or soup.select("div.article-body p") or soup.select("article p")
    date_el = soup.select_one("span.post-date") or soup.select_one("div.post-date") or soup.select_one("p.text-muted")
    title = title_el.get_text(" ", strip=True) if title_el else "Tanpa Judul"
    content = _text_join(body_nodes) or _text_join(soup.find_all("p"))
    published = date_el.get_text(" ", strip=True) if date_el else ""
    return title, content, published


def _parse_article_generic(soup: BeautifulSoup):
    title = soup.title.get_text(" ", strip=True) if soup.title else "Tanpa Judul"
    content = _text_join(soup.find_all("p"))
    return title, content, ""


def _parse_article_by_domain(url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    key = _detect_domain_key(url)

    if key == "detik":
        return key, *_parse_article_detik(soup)
    if key == "kompas":
        return key, *_parse_article_kompas(soup)
    if key == "tempo":
        return key, *_parse_article_tempo(soup)
    if key == "cnn":
        return key, *_parse_article_cnn(soup)
    if key == "republika":
        return key, *_parse_article_republika(soup)
    if key == "antara":
        return key, *_parse_article_antara(soup)

    return "generic", *_parse_article_generic(soup)


def scrape_news_indonesia(
    keyword: str = None,
    url: str = None,
    limit: int = 20,
    debug: bool = False,
    google_max_ratio: float = 0.40,
    max_age_days: float = 5,
):
    if limit < 1:
        return []

    now = dt.datetime.now().isoformat(timespec="seconds")

    if url:
        try:
            r = _requests_get(url, timeout=15)
            text = r.text or ""

            if _is_feed_xml(text):
                feed = feedparser.parse(text)
                entries = getattr(feed, "entries", None) or []
                rows = []
                seen = set()

                for e in entries:
                    if len(rows) >= limit:
                        break
                    link = (e.get("link", "") or "").strip()
                    if not link or link in seen:
                        continue

                    title = e.get("title", "Tanpa Judul")
                    summary = clean_html(e.get("summary", "")) or ""

                    if keyword and not _match_keyword_relaxed(title, summary, keyword):
                        continue

                    seen.add(link)
                    rows.append(_row_from_entry("News - Custom Feed", e, now))

                return rows

            domain_key, title, content, published = _parse_article_by_domain(url, text)

            if keyword and not _match_keyword_relaxed(title, content, keyword):
                return []

            content = (content or "").strip()
            if len(content) > 2500:
                content = content[:2500] + "…"

            return [{
                "source": f"News - {domain_key.upper()}",
                "title": title or "Tanpa Judul",
                "Price/Star": published or "",
                "comment": content if content else "(Konten tidak tersedia)",
                "url": url,
                "scraped_at": now,
            }]

        except Exception as e:
            if debug:
                print(f"[ERROR] Mode URL gagal: {e}")
            return []

    if not keyword:
        return []

    google_max_ratio = max(0.0, min(1.0, float(google_max_ratio)))
    google_cap = int(limit * google_max_ratio)

    google_news_rss = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(keyword)}&hl=id&gl=ID&ceid=ID:id"
    )

    SOURCE_FEEDS = {
        "Google News Indonesia": [google_news_rss],

        "Detik": [
            "https://rss.detik.com/index.php/detikcom",
            "https://rss.detik.com/index.php/detiknews",
            "https://rss.detik.com/index.php/detikcom_nasional",
        ],

        "Kompas": [
            "https://rss.kompas.com/rss/terbaru.xml",
            "https://rss.kompas.com/rss/nasional.xml",
            "https://www.kompas.com/getrss/nasional",
        ],

        "Republika": [
            "https://www.republika.co.id/rss",
            "https://www.republika.co.id/rss/nasional/",
        ],

        "CNN Indonesia": [
            "https://www.cnnindonesia.com/nasional/rss",
            "https://www.cnnindonesia.com/rss",
        ],

        "Tempo": [
            "https://rss.tempo.co/nasional",
            "https://rss.tempo.co/",
        ],

        "Antara": [
            "https://www.antaranews.com/rss/terkini",
            "https://www.antaranews.com/rss/top-news",
        ],

        "Okezone": [
            "https://www.okezone.com/rss",
        ],

        "SindoNews": [
            "https://www.sindonews.com/rss",
        ],
    }

    def parse_feed_url(feed_url: str, name: str):
        feedparser.USER_AGENT = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        f = feedparser.parse(
            feed_url,
            request_headers={
                "User-Agent": feedparser.USER_AGENT,
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            },
        )
        if debug:
            status = getattr(f, "status", None)
            bozo = getattr(f, "bozo", None)
            entries_len = len(getattr(f, "entries", []) or [])
            print(f"[DEBUG] {name} | url={feed_url} | status={status} | entries={entries_len} | bozo={bozo}")
        return f

    def parse_with_fallback(urls: list[str], name: str):
        last = None
        used = ""
        for u in urls:
            try:
                f = parse_feed_url(u, name)
                last = f
                used = u
                if getattr(f, "entries", None):
                    return f, u
            except Exception:
                continue
        return last, used or (urls[0] if urls else "")

    candidates = {name: [] for name in SOURCE_FEEDS.keys()}

    for name, urls in SOURCE_FEEDS.items():
        try:
            feed, used_url = parse_with_fallback(urls, name)
            entries = getattr(feed, "entries", None) or []
            if not entries:
                continue

            for e in entries:
                title = e.get("title", "Tanpa Judul")
                summary = clean_html(e.get("summary", "")) or ""
                link = (e.get("link", "") or "").strip()
                if not link:
                    continue
                if not _match_keyword_relaxed(title, summary, keyword):
                    continue
                if not _entry_age_ok(e, max_age_days):
                    continue
                candidates[name].append(_row_from_entry(f"News - {name}", e, now))

            if debug:
                print(f"[DEBUG] {name} | used={used_url} | candidates={len(candidates[name])}")

        except Exception as e:
            if debug:
                print(f"[ERROR] gagal {name}: {e}")
            continue

    google_name = "Google News Indonesia"
    non_google = [n for n in SOURCE_FEEDS.keys() if n != google_name]

    rows = []
    seen_links = set()

    def pop_unique(name: str, idx_map: dict[str, int]):
        cands = candidates.get(name, [])
        i = idx_map.get(name, 0)
        while i < len(cands) and cands[i]["url"] in seen_links:
            i += 1
        idx_map[name] = i
        if i >= len(cands):
            return None
        item = cands[i]
        idx_map[name] = i + 1
        return item

    target_non_google = max(0, limit - google_cap)
    per_source_cap = (
        -(-target_non_google // len(non_google))
        if target_non_google > 0 else 0
    )

    def count_added(name: str) -> int:
        return sum(1 for r in rows if r["source"] == f"News - {name}")

    def can_add(name: str) -> bool:
        if name == google_name:
            return count_added(name) < google_cap
        return count_added(name) < per_source_cap

    def non_google_count() -> int:
        return sum(1 for r in rows if r["source"] != f"News - {google_name}")

    idx_map = {n: 0 for n in non_google}
    active = [n for n in non_google if candidates.get(n)]

    while non_google_count() < target_non_google and active:
        progressed = False
        for n in list(active):
            if non_google_count() >= target_non_google:
                break
            if not can_add(n):
                active.remove(n)
                continue
            item = pop_unique(n, idx_map)
            if item is None:
                active.remove(n)
                continue
            if item["url"] in seen_links:
                continue
            seen_links.add(item["url"])
            rows.append(item)
            progressed = True
        if not progressed:
            break

    idx_g = {google_name: 0}
    while len(rows) < limit and can_add(google_name):
        item = pop_unique(google_name, idx_g)
        if item is None:
            break
        if item["url"] in seen_links:
            continue
        seen_links.add(item["url"])
        rows.append(item)

    if len(rows) < limit:
        for n in non_google + [google_name]:
            idx_tmp = {n: 0}
            while len(rows) < limit and (n == google_name or can_add(n)):
                item = pop_unique(n, idx_tmp)
                if item is None:
                    break
                if item["url"] in seen_links:
                    continue
                seen_links.add(item["url"])
                rows.append(item)

    if debug:
        def count_src(nm: str) -> int:
            return sum(1 for r in rows if r["source"] == f"News - {nm}")
        print(f"[DEBUG] Total rows: {len(rows)} (limit={limit})")
        for name in SOURCE_FEEDS.keys():
            print(f"[DEBUG] {name}: rows={count_src(name)} candidates={len(candidates.get(name, []))}")
        print(f"[DEBUG] Google cap: {google_cap} (ratio={google_max_ratio}) | per-source cap: {per_source_cap} | max age: {max_age_days} hari")

    return rows