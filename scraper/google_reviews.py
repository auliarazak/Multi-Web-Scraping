from playwright.sync_api import sync_playwright
from urllib.parse import quote_plus
import datetime as dt
import re


def _clean(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _norm_digits(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^\d]", "", s)


def _dismiss_popups(page):
    try:
        page.keyboard.press("Escape")
    except:
        pass

    try:
        not_now = page.locator('button:has-text("Nanti"), button:has-text("Not now")')
        if not_now.count() > 0:
            not_now.first.click(timeout=1200)
    except:
        pass

    try:
        accept = page.locator('button:has-text("Saya setuju"), button:has-text("I agree"), button:has-text("Accept all")')
        if accept.count() > 0:
            accept.first.click(timeout=1200)
    except:
        pass


def _setup_request_blocking(context):
    def handle(route, request):
        try:
            rtype = request.resource_type
            if rtype in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        except:
            try:
                route.continue_()
            except:
                pass

    try:
        context.route("**/*", handle)
    except:
        pass


def _extract_city_country(address: str, fallback_city: str, fallback_country: str = "Indonesia"):
    city = _clean(fallback_city)
    country = fallback_country
    if address and "indonesia" in address.lower():
        country = "Indonesia"
    return city, country


def _format_rating(rating_raw: str) -> str:
    rating_raw = _clean(rating_raw)
    if not rating_raw:
        return ""
    rating_raw = rating_raw.replace(".", ",")
    m = re.search(r"\b([0-5](?:[.,]\d)?)\b", rating_raw)
    if not m:
        return ""
    val = m.group(1).replace(".", ",")
    return f"{val} bintang"


def _parse_price_range_text(s: str) -> str:
    s = _clean(s)
    if not s:
        return ""
    m = re.search(
        r"(Rp\s*[\d\.\,]+\s*(?:rb|ribu|jt|juta)?\s*[–-]\s*[\d\.\,]+\s*(?:rb|ribu|jt|juta)?)",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return _clean(m.group(1))
    m = re.search(r"(Rp\s*[\d\.\,]+\s*[–-]\s*[\d\.\,]+)", s, flags=re.IGNORECASE)
    if m:
        return _clean(m.group(1))
    return ""


def _looks_like_address(s: str) -> bool:
    if not s:
        return False
    t = s.lower()
    if "rp" in t:
        return False
    if "bintang" in t or "ulasan" in t or "review" in t:
        return False
    if re.search(r"\b(jl\.|jalan|no\.|nomor|rt\b|rw\b|kec\.|kecamatan|kel\.|kelurahan|nagari|kota|kab\.|kabupaten)\b", t):
        return True
    if len(s) >= 18 and re.search(r"\d", s) and ("," in s or "-" in s):
        return True
    return False


def _pick_category_from_parts(parts, title=""):
    title_l = _clean(title).lower()
    if not parts:
        return ""

    def is_noise(x: str) -> bool:
        xl = x.lower()
        if not xl:
            return True
        if xl == title_l:
            return True
        if _looks_like_address(x):
            return True
        if "rp" in xl:
            return True
        if "bintang" in xl or "ulasan" in xl or "review" in xl:
            return True
        if "buka" in xl or "tutup" in xl or "jam" in xl or "menit" in xl:
            return True
        if re.search(r"\b([0-5](?:[.,]\d)?)\b", xl):
            return True
        if len(x) > 45:
            return True
        if re.fullmatch(r"[\d\.\,\(\)\s·\-–]+", x):
            return True
        return False

    keywords = [
        "kedai", "kafe", "cafe", "restoran", "rumah makan", "warung",
        "toko", "roastery", "bakery", "coffee", "kopi"
    ]

    candidates = []
    for p in parts:
        pp = _clean(p)
        if not pp or is_noise(pp):
            continue
        candidates.append(pp)

    if not candidates:
        return ""

    kw_hits = [c for c in candidates if any(k in c.lower() for k in keywords)]
    if kw_hits:
        kw_hits.sort(key=lambda x: (len(x), x))
        return kw_hits[0]

    candidates.sort(key=lambda x: (len(x), x))
    return candidates[0]


def _parse_review_count_from_any(text: str) -> str:
    text = _clean(text)
    if not text:
        return ""

    m = re.search(r"\b[0-5](?:[.,]\d)?\s*\(\s*([\d\.\,]+)\s*\)", text)
    if m:
        return _norm_digits(m.group(1))

    m = re.search(r"([\d\.\,]+)\s*ulasan", text.lower())
    if m:
        return _norm_digits(m.group(1))

    return ""


def _extract_panel_items(page):
    items_map = {}

    def harvest():
        try:
            data = page.eval_on_selector_all(
                "a.hfpxzc",
                """
                (els) => els.map(a => {
                    const href = a.href || "";
                    const title = (a.getAttribute('aria-label') || a.textContent || "").trim();

                    const card =
                        a.closest('div.Nv2PK') ||
                        a.closest('div[role="article"]') ||
                        a.parentElement;

                    let ratingRaw = "";
                    let countRaw = "";
                    let parts = [];
                    let text = "";

                    if (card) {
                        text = (card.innerText || "").trim();

                        const r = card.querySelector('span.MW4etd');
                        if (r) ratingRaw = (r.textContent || "").trim();

                        // count panel kadang ada, kadang tidak
                        const c = card.querySelector('span.UY7F9');
                        if (c) countRaw = (c.textContent || "").trim();

                        const spans = card.querySelectorAll('div.W4Efsd span');
                        spans.forEach(s => {
                            const t = (s.textContent || "").trim();
                            if (t) parts.push(t);
                        });
                    }

                    return { href, title, ratingRaw, countRaw, parts, text };
                })
                """,
            )
        except:
            data = []

        for it in data or []:
            href = _clean(it.get("href", ""))
            if not href:
                continue

            cur = items_map.get(href, {})

            title = _clean(it.get("title", "")) or cur.get("title", "")
            rating_raw = _clean(it.get("ratingRaw", "")) or cur.get("rating_raw", "")
            count_raw = _clean(it.get("countRaw", "")) or cur.get("count_raw", "")
            text = _clean(it.get("text", "")) or cur.get("text", "")

            parts_new = it.get("parts", []) or []
            parts_old = cur.get("parts", []) or []
            merged, seen = [], set()
            for x in parts_old + parts_new:
                xx = _clean(x)
                if not xx:
                    continue
                if xx not in seen:
                    seen.add(xx)
                    merged.append(xx)

            address = cur.get("address", "")
            if not address and merged:
                addr_candidates = [p for p in merged if _looks_like_address(p)]
                if addr_candidates:
                    addr_candidates.sort(key=len)
                    address = addr_candidates[-1]

            category = cur.get("category", "")
            if not category and merged:
                category = _pick_category_from_parts(merged, title=title)

            price_range = cur.get("price_range", "")
            if not price_range and merged:
                for p in merged:
                    pr = _parse_price_range_text(p)
                    if pr:
                        price_range = pr
                        break
            if not price_range:
                price_range = _parse_price_range_text(text) or price_range

            review_count = cur.get("review_count", "")
            if not review_count:
                if count_raw:
                    review_count = _norm_digits(count_raw)
                if not review_count:
                    review_count = _parse_review_count_from_any(text)

            items_map[href] = {
                "title": title,
                "rating_raw": rating_raw,
                "count_raw": count_raw,
                "review_count": _clean(review_count),
                "parts": merged,
                "text": text,
                "address": _clean(address),
                "category": _clean(category),
                "price_range": _clean(price_range),
            }

    harvest()
    return items_map, harvest


def _detail_extract_address(page) -> str:
    try:
        btn = page.locator('button[data-item-id="address"]').first
        if btn.count() > 0:
            aria = _clean(btn.get_attribute("aria-label") or "")
            txt = _clean(btn.inner_text() or "")
            cand = aria or txt
            cand = _clean(cand)
            if cand.lower().startswith("alamat"):
                cand = cand.split(":", 1)[-1].strip()
            return cand
    except:
        pass
    return ""


def _detail_extract_review_count(page) -> str:
    try:
        btn = page.locator('button[jsaction*="pane.rating.moreReviews"]').first
        if btn.count() > 0:
            aria = _clean(btn.get_attribute("aria-label") or "")
            txt = _clean(btn.inner_text() or "")
            cand = aria or txt
            got = _parse_review_count_from_any(cand)
            if got:
                return got
            m = re.search(r"([\d\.\,]+)", cand)
            if m:
                return _norm_digits(m.group(1))
    except:
        pass

    try:
        block = page.locator("div.F7nice").first
        if block.count() > 0:
            raw = _clean(block.inner_text() or "")
            got = _parse_review_count_from_any(raw)
            if got:
                return got
            m = re.search(r"\(([\d\.\,]+)\)", raw)
            if m:
                return _norm_digits(m.group(1))
    except:
        pass

    return ""


def _detail_backfill(page, href: str):
    cat = ""
    price = ""
    addr = ""
    cnt = ""

    try:
        page.goto(href, wait_until="domcontentloaded", timeout=30000)
        _dismiss_popups(page)
        page.wait_for_timeout(900)

        addr = _detail_extract_address(page)

        cnt = _detail_extract_review_count(page)
        try:
            parts = page.locator('div.W4Efsd span').all_inner_texts()
            parts = [_clean(x) for x in parts if _clean(x)]
        except:
            parts = []

        if parts:
            cat = _pick_category_from_parts(parts)
            for p in parts:
                pr = _parse_price_range_text(p)
                if pr:
                    price = pr
                    break
        if not price:
            try:
                body = page.locator("body").inner_text(timeout=4000)
                price = _parse_price_range_text(body)
            except:
                pass

    except:
        pass

    return _clean(cat), _clean(price), _clean(addr), _clean(cnt)


_COORD_RE = re.compile(r"^-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$")


def _build_search_url(place_name: str, location: str = "") -> str:
    place = (place_name or "").strip()
    loc = (location or "").strip()
    if loc and loc.lower() not in place.lower():
        if _COORD_RE.match(loc):
            query = f"{place} {loc}"
        else:
            query = f"{place} di {loc}"
    else:
        query = place
    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={quote_plus(query)}"
    )


def _scroll_rounds_for_limit(limit: int, scroll_rounds=None) -> int:
    derived = max(10, (int(limit or 30) + 4) // 5)
    if scroll_rounds is not None:
        derived = max(derived, int(scroll_rounds))
    return int(max(3, min(derived, 35)))


def scrape_google_reviews_by_name(
    place_name: str,
    headless: bool = False,
    limit: int = 30,
    scroll_rounds: int = 12,
    wait: float = 0.35,
    location: str = "",
    fallback_country: str = "Indonesia",
    backfill_max: int = None,
    placeholder: str = "-",
    stop_event=None,
):
    """
    Output rows:
    {
      source, title, category, price_range, review_count, rating,
      address, country, city, url, scraped_at
    }
    """
    place_name = (place_name or "").strip()
    if not place_name:
        return []

    limit = int(max(1, min(limit or 1, 500)))
    scroll_rounds = _scroll_rounds_for_limit(limit, scroll_rounds)
    wait_ms = int(max(120, min(int((wait or 0.35) * 1000), 1400)))

    loc = (location or "").strip()
    search_url = _build_search_url(place_name, loc)

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            locale="id-ID",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        _setup_request_blocking(context)

        page = context.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(25000)

        print("[DEBUG] Membuka Google Maps (panel + backfill)...")
        page.goto(search_url, wait_until="domcontentloaded")
        _dismiss_popups(page)

        try:
            page.wait_for_selector('div[role="feed"] a.hfpxzc', timeout=15000)
        except:
            pass

        feed = None
        feed_candidates = page.locator('div[role="feed"]')
        for i in range(min(feed_candidates.count(), 6)):
            cand = feed_candidates.nth(i)
            try:
                if cand.locator("a.hfpxzc").count() > 0:
                    feed = cand
                    break
            except:
                continue
        if feed is None:
            feed = page.locator('div.m6QErb.DxyBCb.kA9KIf.dS8AEf.ecceSd').first

        items_map, harvest = _extract_panel_items(page)

        last_size = len(items_map)
        stagnant = 0

        for _ in range(scroll_rounds):
            if len(items_map) >= limit:
                break
            if stop_event is not None and stop_event.is_set():
                break
            try:
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
            except:
                try:
                    page.mouse.wheel(0, 2200)
                except:
                    pass
            page.wait_for_timeout(wait_ms)
            _dismiss_popups(page)

            harvest()
            if len(items_map) == last_size:
                stagnant += 1
            else:
                stagnant = 0
                last_size = len(items_map)
            if stagnant >= 3:
                break

        hrefs = list(items_map.keys())[:limit]
        for href in hrefs:
            meta = items_map[href]
            title = _clean(meta.get("title", "")) or "Unknown Place"
            text = _clean(meta.get("text", ""))

            rating = _format_rating(meta.get("rating_raw", ""))
            review_count = _clean(meta.get("review_count", ""))

            if not rating:
                m = re.search(r"\b([0-5](?:[.,]\d)?)\b", text)
                if m:
                    rating = _format_rating(m.group(1))

            if not review_count:
                review_count = _parse_review_count_from_any(text)

            address = _clean(meta.get("address", ""))
            category = _clean(meta.get("category", ""))
            price_range = _clean(meta.get("price_range", ""))

            city_out, country_out = _extract_city_country(address, fallback_city=loc, fallback_country=fallback_country)

            rows.append({
                "source": "Google Reviews",
                "title": title,
                "category": category,
                "price_range": price_range,
                "review_count": review_count,
                "rating": rating,
                "address": address,
                "country": country_out,
                "city": city_out,
                "url": href,
                "scraped_at": now,
            })

        need_idx = [
            i for i, r in enumerate(rows)
            if (not r.get("category") or not r.get("price_range") or not r.get("review_count") or not r.get("address"))
        ]

        if backfill_max is None:
            backfill_max = len(need_idx)
        else:
            backfill_max = int(max(0, min(backfill_max, len(need_idx))))
        need_idx = need_idx[:backfill_max]

        if need_idx:
            print(f"[DEBUG] Backfill detail untuk {len(need_idx)} item (field kosong)...")

        for i in need_idx:
            if stop_event is not None and stop_event.is_set():
                break
            href = rows[i].get("url", "")
            if not href:
                continue
            cat, price, addr, cnt = _detail_backfill(page, href)

            if cat and not rows[i].get("category"):
                rows[i]["category"] = cat
            if price and not rows[i].get("price_range"):
                rows[i]["price_range"] = price
            if addr and not rows[i].get("address"):
                rows[i]["address"] = addr
                rows[i]["city"], rows[i]["country"] = _extract_city_country(addr, fallback_city=loc, fallback_country=fallback_country)
            if cnt and not rows[i].get("review_count"):
                rows[i]["review_count"] = cnt

        for r in rows:
            if not r.get("category"):
                r["category"] = placeholder
            if not r.get("price_range"):
                r["price_range"] = placeholder
            if not r.get("review_count"):
                r["review_count"] = placeholder
            if not r.get("address"):
                r["address"] = placeholder

        try:
            context.close()
        except:
            pass
        browser.close()

    print(f"[DEBUG] Total data terkumpul (panel+backfill): {len(rows)}")
    return rows