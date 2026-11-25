from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://research.google"
ROBOTS_URL = f"{BASE}/robots.txt"

DEBUG = False
MAX_SCAN = 3000
PUB_URL_CACHE_DAYS = 7
PUB_URL_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "research_pub_urls.json"
)
FAST_WAIT_MS = 30
GOTO_TIMEOUT_MS = 45000
WAIT_H1_TIMEOUT_MS = 9000


def _clean(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _extract_year(text: str) -> str:
    m = re.search(r"\b(19|20)\d{2}\b", text or "")
    return m.group(0) if m else ""


def _normalize_pub_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/pubs/"):
        return urljoin(BASE, u)
    if u.startswith("pubs/"):
        return urljoin(BASE + "/", u)

    slug = u.strip("/")
    if "/" in slug:
        slug = slug.split("/")[-1].strip()
    return f"{BASE}/pubs/{slug}/"


def _kw_match_title_only(title: str, kw: str) -> bool:
    kw = (kw or "").strip().lower()
    if not kw:
        return True
    title = (title or "").lower()
    terms = [t for t in re.split(r"\s+", kw) if len(t) >= 3]
    if not terms:
        return kw in title
    return all(t in title for t in terms)


def _dismiss_overlays(page):
    candidates = [
        "I agree", "Accept all", "Accept", "Agree", "OK", "Got it",
        "Setuju", "Terima semua", "Terima", "Saya setuju", "Lanjut",
    ]
    for t in candidates:
        try:
            btn = page.get_by_role("button", name=t, exact=False).first
            if btn and btn.is_visible():
                btn.click(timeout=1200)
                page.wait_for_timeout(250)
        except Exception:
            pass


def _goto_fast(page, url: str):
    page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    _dismiss_overlays(page)
    try:
        page.wait_for_selector("h1", timeout=WAIT_H1_TIMEOUT_MS)
    except Exception:
        pass
    _dismiss_overlays(page)


def _req_get(ctx, url: str, timeout_ms: int = 25000, retries: int = 1) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = ctx.request.get(url, timeout=timeout_ms)
            if DEBUG:
                try:
                    print("DEBUG REQ GET:", url, "status:", resp.status)
                except Exception:
                    pass
            if resp.ok:
                return resp.text()
            last_exc = RuntimeError(f"HTTP {resp.status} saat GET {url}")
        except Exception as e:  # noqa: BLE001 — simpan, coba lagi / lempar
            last_exc = e
        if attempt < retries:
            time.sleep(1.0)
    raise last_exc


def _extract_abstract_structured(soup: BeautifulSoup) -> str:
    heading_candidates = soup.find_all(
        lambda tag: tag.name in ("h1", "h2", "h3", "h4", "strong", "span", "div")
        and _clean(tag.get_text(" ", strip=True)).lower() == "abstract"
    )

    for h in heading_candidates:
        container = h.find_parent(["section", "div", "article"]) or h.parent
        if not container:
            continue

        text_parts = []
        started = False
        for child in container.descendants:
            if child == h:
                started = True
                continue
            if not started:
                continue
            if getattr(child, "name", None) in ("h1", "h2", "h3") and _clean(child.get_text(" ", strip=True)):
                break
            if getattr(child, "name", None) in ("p", "div", "span"):
                t = _clean(child.get_text(" ", strip=True))
                if t and t.lower() not in ("copy bibtex", "cite", "bibtex", "google scholar"):
                    text_parts.append(t)

        abstract = _clean(" ".join(text_parts))
        if len(abstract) >= 80:
            return abstract

    for tag in soup.find_all(True):
        for attr in ("aria-label", "data-title", "data-section", "id", "class"):
            v = tag.get(attr)
            if not v:
                continue
            vv = " ".join(v) if isinstance(v, list) else str(v)
            if "abstract" in vv.lower():
                t = _clean(tag.get_text(" ", strip=True))
                if len(t) >= 80:
                    return t

    main = soup.find("main") or soup.find("article") or soup
    ps = main.find_all("p")
    for p in ps:
        t = _clean(p.get_text(" ", strip=True))
        if len(t) >= 120 and "cookie" not in t.lower() and "consent" not in t.lower():
            return t

    return ""


def _parse_detail_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True) if h1 else "")

    main = soup.find("main") or soup
    lines = [_clean(x) for x in main.get_text("\n", strip=True).split("\n")]
    lines = [x for x in lines if x]

    if not title and "Abstract" not in lines:
        snippet = _clean(" ".join(lines[:40]))
        raise RuntimeError(
            f"Halaman detail tidak valid / kemungkinan consent/block. URL={url} | snippet={snippet[:200]}"
        )

    abstract = _extract_abstract_structured(soup)

    if not abstract and "Abstract" in lines:
        i = lines.index("Abstract")
        buf = []
        for x in lines[i + 1:]:
            low = x.lower()
            if low.startswith("learn more about") or low.startswith("follow us"):
                break
            if low in ("search", "copy bibtex", "cite", "bibtex"):
                continue
            buf.append(x)
        abstract = _clean(" ".join(buf))

    year = ""
    for x in lines:
        y = _extract_year(x)
        if y:
            year = y
            break

    authors = []
    if title and title in lines:
        i_title = lines.index(title)
        end = lines.index("Abstract") if "Abstract" in lines else min(len(lines), i_title + 60)
        pre = lines[i_title + 1:end]

        venue_idx = None
        for j, x in enumerate(pre):
            if _extract_year(x):
                venue_idx = j
                break
        cand = pre[:venue_idx] if venue_idx is not None else pre

        for x in cand:
            low = x.lower()
            if low in ("preview", "preview abstract", "view details", "google scholar", "copy bibtex"):
                continue
            if len(x) > 240 and any(p in x for p in ".;:"):
                break
            authors.append(x)

    return {
        "source": "Google Research",
        "title": title,
        "authors": "; ".join([a for a in authors if a]),
        "year": year,
        "abstract": abstract,
        "url": url,
    }


def _discover_sitemaps(ctx) -> list[str]:
    try:
        txt = _req_get(ctx, ROBOTS_URL)
    except Exception:
        txt = ""

    sitemaps = []
    for line in txt.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sm = line.split(":", 1)[1].strip()
            if sm:
                sitemaps.append(sm)

    if not sitemaps:
        sitemaps = [f"{BASE}/sitemap.xml", f"{BASE}/sitemap_index.xml"]

    out, seen = [], set()
    for s in sitemaps:
        if s not in seen:
            seen.add(s)
            out.append(s)

    if DEBUG:
        print("DEBUG SITEMAPS:", out[:5], "count:", len(out))
    return out


def _parse_sitemap_locs(xml_text: str) -> list[str]:
    soup = BeautifulSoup(xml_text, "xml")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc") if loc.get_text(strip=True)]


def _collect_pub_urls_from_sitemaps(ctx, max_sitemaps: int = 20, max_pub_urls: int = 20000) -> list[str]:
    seeds = _discover_sitemaps(ctx)
    if not seeds:
        return []

    pub_urls = []
    seen_pub = set()

    queue = list(seeds)
    visited = set()

    def add_pub(u: str):
        if "/pubs/" not in u:
            return
        u = u.split("?")[0].strip()
        if u.rstrip("/") in (f"{BASE}/pubs", f"{BASE}/pubs/"):
            return
        key = u.rstrip("/")
        if key not in seen_pub:
            seen_pub.add(key)
            pub_urls.append(u)

    while queue and len(visited) < max_sitemaps and len(pub_urls) < max_pub_urls:
        sm_url = queue.pop(0)
        if sm_url in visited:
            continue
        visited.add(sm_url)

        try:
            xml = _req_get(ctx, sm_url)
        except Exception as e:
            if DEBUG:
                print("DEBUG sitemap fetch failed:", sm_url, e)
            continue

        locs = _parse_sitemap_locs(xml)

        child = [u for u in locs if u.lower().endswith((".xml", ".xml.gz"))]
        if child:
            for u in child[:max_sitemaps]:
                if u not in visited:
                    queue.append(u)
            continue

        for u in locs:
            add_pub(u)

    if DEBUG:
        print("DEBUG PUB URLS FROM SITEMAP:", len(pub_urls))
    return pub_urls


def _load_pub_url_cache(max_age_days: float | None = PUB_URL_CACHE_DAYS) -> list[str]:
    try:
        with open(PUB_URL_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        urls = [u for u in (data.get("urls") or []) if isinstance(u, str) and "/pubs/" in u]
        if not urls:
            return []
        if max_age_days is not None:
            saved = float(data.get("saved_at") or 0)
            if time.time() - saved > max_age_days * 86400:
                return []
        if DEBUG:
            print("DEBUG PUB URL CACHE HIT:", len(urls), "dari", PUB_URL_CACHE_FILE)
        return urls
    except Exception:
        return []


def _save_pub_url_cache(urls: list[str]) -> None:
    try:
        tmp = PUB_URL_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "urls": list(urls)}, f)
        os.replace(tmp, PUB_URL_CACHE_FILE)
    except Exception:
        pass


def _get_pub_urls(ctx) -> list[str]:
    urls = _load_pub_url_cache()
    if urls:
        return urls
    urls = _collect_pub_urls_from_sitemaps(ctx, max_sitemaps=20, max_pub_urls=20000)
    if urls:
        _save_pub_url_cache(urls)
        return urls
    return _load_pub_url_cache(max_age_days=None)


_SUGGEST_STOPWORDS = {
    "the", "and", "for", "with", "from", "using", "into", "over", "under",
    "via", "per", "towards", "toward", "between", "among", "upon", "after",
    "before", "without", "within", "through", "during", "against", "based",
}


def _slug_tokens(url: str) -> list[str]:
    slug = (url or "").rstrip("/").rsplit("/", 1)[-1].lower()
    return [
        t for t in slug.split("-")
        if len(t) >= 3 and t.isalpha() and t not in _SUGGEST_STOPWORDS
    ]


def suggest_keywords(top_words: int = 15, top_pairs: int = 6,
                     min_word_count: int = 50, min_pair_count: int = 20) -> dict:
    urls = _load_pub_url_cache(max_age_days=None)
    if not urls:
        return {"words": [], "pairs": []}
    seen: set[str] = set()
    word_counts: Counter = Counter()
    pair_counts: Counter = Counter()
    for u in urls:
        key = u.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        tokens = _slug_tokens(u)
        for t in set(tokens):
            word_counts[t] += 1
        for a, b in zip(tokens, tokens[1:]):
            pair_counts[(a, b)] += 1
    words = [
        {"keyword": w, "count": n}
        for w, n in word_counts.most_common(top_words) if n >= min_word_count
    ]
    pairs = [
        {"keyword": f"{a} {b}", "count": n}
        for (a, b), n in pair_counts.most_common(top_pairs)
        if n >= min_pair_count
    ]
    return {"words": words, "pairs": pairs}

def scrape_google_research(
    keyword: str | None = None,
    url: str | None = None,
    headless: bool = True,
    limit: int = 20,
    scroll_rounds: int = 30,
    wait: float = 0.0,
    stop_event=None,
) -> list[dict]:
    limit = max(1, int(limit))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        if url:
            u = _normalize_pub_url(url)
            if not u:
                ctx.close()
                browser.close()
                return []
            _goto_fast(page, u)
            item = _parse_detail_html(page.content(), u)
            ctx.close()
            browser.close()
            return [item]

        kw = (keyword or "").strip()
        if not kw:
            ctx.close()
            browser.close()
            return []

        pub_urls = _get_pub_urls(ctx)
        if not pub_urls:
            ctx.close()
            browser.close()
            raise RuntimeError("Tidak bisa mendapatkan daftar publikasi (sitemap kosong / diblok).")

        kw_lower = kw.lower()
        urls_hit = [u for u in pub_urls if kw_lower in u.lower()]
        urls_miss = [u for u in pub_urls if kw_lower not in u.lower()]
        scan_urls = urls_hit + urls_miss

        if MAX_SCAN and len(scan_urls) > MAX_SCAN:
            scan_urls = scan_urls[:MAX_SCAN]

        out = []
        scanned = 0
        seen_scan = set()

        for u in scan_urls:
            if len(out) >= limit:
                break
            if stop_event is not None and stop_event.is_set():
                break
            key = u.rstrip("/")
            if key in seen_scan:
                continue
            seen_scan.add(key)
            scanned += 1
            try:
                _goto_fast(page, u)
                item = _parse_detail_html(page.content(), u)

                if not _kw_match_title_only(item.get("title", ""), kw):
                    continue

                out.append(item)
            except Exception:
                continue
            finally:
                if FAST_WAIT_MS:
                    page.wait_for_timeout(FAST_WAIT_MS)

        ctx.close()
        browser.close()
        return out