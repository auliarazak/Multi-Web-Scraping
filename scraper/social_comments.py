import datetime as dt
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def _platform_from_url(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "x.com" in host or "twitter.com" in host:
        return "X"
    if "threads.net" in host:
        return "Threads"
    if "instagram.com" in host:
        return "Instagram"
    if "tiktok.com" in host:
        return "TikTok"
    return "Unknown"


def _dismiss_common_popups(page):
    candidates = [
        'button:has-text("Not now")',
        'button:has-text("Nanti")',
        'button:has-text("Close")',
        'button:has-text("Tutup")',
        'button[aria-label="Close"]',
        'button[aria-label="Tutup"]',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=1500)
                page.wait_for_timeout(600)
        except:
            pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except:
        pass


def _result_info_row(platform: str, url: str, message: str, now: str):
    return [{
        "source": f"Social - {platform}",
        "title": f"{platform} Post",
        "Price/Star": "",
        "comment": message,
        "url": url,
        "scraped_at": now
    }]


def _scrape_x(page, url: str, limit: int, now: str, debug: bool):
    page.goto(url, timeout=60000)
    page.wait_for_timeout(4000)
    _dismiss_common_popups(page)

    for _ in range(4):
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(900)
        _dismiss_common_popups(page)

    reply_texts = []
    try:

        nodes = page.locator('div[data-testid="tweetText"]')
        n = nodes.count()
        if debug:
            print(f"[DEBUG] X: tweetText nodes ditemukan = {n}")

        for i in range(min(n, limit + 3)):
            txt = nodes.nth(i).inner_text().strip()
            if txt:
                reply_texts.append(txt)
            if len(reply_texts) >= limit:
                break
    except Exception as e:
        if debug:
            print(f"[DEBUG] X parse error: {e}")

    if not reply_texts:
        return _result_info_row(
            "X",
            url,
            "Komentar tidak terbaca. Kemungkinan: konten butuh login / dibatasi / terblokir oleh X.",
            now
        )

    rows = []
    for t in reply_texts[:limit]:
        rows.append({
            "source": "Social - X",
            "title": "X Reply",
            "Price/Star": "",
            "comment": t,
            "url": url,
            "scraped_at": now
        })
    return rows


def _scrape_tiktok(page, url: str, limit: int, now: str, debug: bool):

    page.goto(url, timeout=60000)
    page.wait_for_timeout(4500)
    _dismiss_common_popups(page)

    for _ in range(5):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1000)
        _dismiss_common_popups(page)

    comments = []
    try:
        items = page.locator('div[data-e2e="comment-item"]')
        n = items.count()
        if debug:
            print(f"[DEBUG] TikTok: comment-item ditemukan = {n}")

        for i in range(min(n, limit)):
            item = items.nth(i)
            txt = ""
            try:
                p = item.locator("p")
                if p.count() > 0:
                    txt = p.first.inner_text().strip()
            except:
                txt = ""
            if txt:
                comments.append(txt)
    except Exception as e:
        if debug:
            print(f"[DEBUG] TikTok parse error: {e}")

    if not comments:
        return _result_info_row(
            "TikTok",
            url,
            "Komentar tidak terbaca. Kemungkinan: konten butuh login / region blocked / halaman berubah.",
            now
        )

    return [{
        "source": "Social - TikTok",
        "title": "TikTok Comment",
        "Price/Star": "",
        "comment": c,
        "url": url,
        "scraped_at": now
    } for c in comments[:limit]]


def _scrape_threads(page, url: str, limit: int, now: str, debug: bool):
    page.goto(url, timeout=60000)
    page.wait_for_timeout(4500)
    _dismiss_common_popups(page)

    # Scroll
    for _ in range(4):
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(900)
        _dismiss_common_popups(page)

    comments = []
    try:
        nodes = page.locator("article div, article span")
        n = nodes.count()
        if debug:
            print(f"[DEBUG] Threads: candidate nodes = {n}")

        for i in range(min(n, 500)):
            txt = nodes.nth(i).inner_text().strip()
            # filter text yang terlalu pendek
            if 8 <= len(txt) <= 400:
                comments.append(txt)
            if len(comments) >= limit:
                break
    except Exception as e:
        if debug:
            print(f"[DEBUG] Threads parse error: {e}")

    if not comments:
        return _result_info_row(
            "Threads",
            url,
            "Komentar tidak terbaca. Threads biasanya butuh login / proteksi anti-bot tinggi.",
            now
        )

    return [{
        "source": "Social - Threads",
        "title": "Threads Comment",
        "Price/Star": "",
        "comment": c,
        "url": url,
        "scraped_at": now
    } for c in comments[:limit]]


def _scrape_instagram(page, url: str, limit: int, now: str, debug: bool):

    page.goto(url, timeout=60000)
    page.wait_for_timeout(4500)
    _dismiss_common_popups(page)

    for _ in range(3):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(900)
        _dismiss_common_popups(page)

    comments = []
    try:
        nodes = page.locator("ul li span")
        n = nodes.count()
        if debug:
            print(f"[DEBUG] IG: ul li span nodes = {n}")

        for i in range(min(n, 400)):
            txt = nodes.nth(i).inner_text().strip()
            if 8 <= len(txt) <= 400:
                comments.append(txt)
            if len(comments) >= limit:
                break
    except Exception as e:
        if debug:
            print(f"[DEBUG] IG parse error: {e}")

    if not comments:
        return _result_info_row(
            "Instagram",
            url,
            "Komentar tidak terbaca. Instagram biasanya butuh login / proteksi anti-bot tinggi.",
            now
        )

    return [{
        "source": "Social - Instagram",
        "title": "Instagram Comment",
        "Price/Star": "",
        "comment": c,
        "url": url,
        "scraped_at": now
    } for c in comments[:limit]]


def scrape_social_comments_by_url(
    post_url: str,
    headless: bool = False,
    limit: int = 40,
    debug: bool = True
):
    if not post_url:
        return []

    now = dt.datetime.now().isoformat(timespec="seconds")
    platform = _platform_from_url(post_url)

    if debug:
        print(f"[DEBUG] Social scraper platform: {platform}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
        )
        context = browser.new_context(
            locale="id-ID",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        try:
            if platform == "X":
                rows = _scrape_x(page, post_url, limit, now, debug)
            elif platform == "TikTok":
                rows = _scrape_tiktok(page, post_url, limit, now, debug)
            elif platform == "Threads":
                rows = _scrape_threads(page, post_url, limit, now, debug)
            elif platform == "Instagram":
                rows = _scrape_instagram(page, post_url, limit, now, debug)
            else:
                rows = _result_info_row(
                    "Unknown",
                    post_url,
                    "Platform tidak dikenali. Gunakan URL dari: x.com / threads.net / instagram.com / tiktok.com",
                    now
                )
        finally:
            browser.close()

    if debug:
        print(f"[DEBUG] Total data terkumpul: {len(rows)}")

    return rows
