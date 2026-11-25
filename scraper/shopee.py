import os
import time
import random
import datetime as dt
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

from parser.shopee_parser import parse_products
from config import BASE_DIR, RUNTIME_DIR


SHOPEE_HOME = "https://shopee.co.id/"
_LEGACY_PROFILE = os.path.join(BASE_DIR, "pw_shopee_profile")
PROFILE_DIR = (_LEGACY_PROFILE if os.path.isdir(_LEGACY_PROFILE)
               else os.path.join(RUNTIME_DIR, "pw_shopee_profile"))
DEBUG_HTML_FILE = os.path.join(RUNTIME_DIR, "debug_shopee.html")


def build_search_url(keyword: str) -> str:
    return f"https://shopee.co.id/search?keyword={quote_plus(keyword)}"


def looks_like_search(url: str) -> bool:
    try:
        u = urlparse(url)
        return "shopee.co.id" in u.netloc and "/search" in u.path
    except Exception:
        return False


def _is_login_url(url: str) -> bool:
    u = (url or "").lower()
    return "/buyer/login" in u or "/login" in u


def _is_captcha_url(url: str) -> bool:
    u = (url or "").lower()
    return "/verify/captcha" in u or "captcha" in u


def _write_debug_html(html: str):
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(DEBUG_HTML_FILE, "w", encoding="utf-8") as f:
            f.write(html or "")
    except Exception:
        pass


def _human_pause(a=0.8, b=1.6):
    time.sleep(random.uniform(a, b))


def _wait_soft(page, timeout_ms=15000):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def _warmup(page):
    page.goto(SHOPEE_HOME, wait_until="domcontentloaded", timeout=60000)
    _human_pause(4.0, 6.0)
    _wait_soft(page, 12000)

    try:
        page.mouse.move(200, 220)
        _human_pause(0.3, 0.7)
        page.mouse.wheel(0, 350)
        _human_pause(1.0, 1.8)
        page.mouse.wheel(0, 500)
        _human_pause(1.0, 1.8)
        page.mouse.wheel(0, -180)
        _human_pause(0.8, 1.3)
    except Exception:
        pass


def _wait_manual_clear(page, timeout_sec=180):
    print("\n[Shopee] Jika muncul login / captcha, selesaikan manual di browser.")
    print(f"[Shopee] Menunggu sampai {timeout_sec} detik...\n")

    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            cur = page.url.lower()
            if "shopee.co.id" in cur and (not _is_login_url(cur)) and (not _is_captcha_url(cur)):
                _human_pause(2.0, 3.0)
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _human_scroll(page, scroll_rounds=10, wait=1.3):
    last_h = 0
    for i in range(scroll_rounds):
        try:
            step = random.randint(450, 900)
            page.mouse.wheel(0, step)
            _human_pause(wait, wait + 0.9)
            h = page.evaluate("() => document.body.scrollHeight")
            if h == last_h and i >= 2:
                break
            last_h = h
        except Exception:
            break


def scrape_shopee(
    keyword: str = None,
    url: str = None,
    headless: bool = True,
    limit: int = 100,
    scroll_rounds: int = 10,
    wait: float = 1.3
):
    if keyword and not url:
        target = build_search_url(keyword)
    elif url:
        if not looks_like_search(url):
            raise ValueError("URL Shopee harus halaman search (/search?keyword=...).")
        target = url
    else:
        raise ValueError("Masukkan keyword atau URL Shopee search.")

    os.makedirs(PROFILE_DIR, exist_ok=True)

    html = ""
    final_url = ""

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,  # MODE 1: selalu visible
            channel="chrome",
            viewport={"width": 1366, "height": 900},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--lang=id-ID",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()

            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['id-ID', 'id', 'en-US', 'en']
                });
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'Win32'
                });
            """)

            _warmup(page)

            page.goto(target, wait_until="domcontentloaded", timeout=60000)
            _human_pause(4.0, 6.0)
            _wait_soft(page, 15000)

            cur = page.url.lower()
            if _is_login_url(cur) or _is_captcha_url(cur):
                ok = _wait_manual_clear(page, timeout_sec=180)
                if not ok:
                    raise RuntimeError(
                        "Login/captcha Shopee belum selesai dalam 180 detik."
                    )

                page.goto(target, wait_until="domcontentloaded", timeout=60000)
                _human_pause(4.0, 6.0)
                _wait_soft(page, 15000)
                cur = page.url.lower()

            if _is_login_url(cur):
                raise RuntimeError("Shopee masih mengembalikan halaman login, bukan hasil pencarian.")

            if _is_captcha_url(cur):
                raise RuntimeError("Shopee masih mengembalikan halaman captcha, bukan hasil pencarian.")

            _human_scroll(page, scroll_rounds=scroll_rounds, wait=wait)
            _human_pause(2.0, 3.0)

            final_url = page.url
            html = page.content()
            _write_debug_html(html)

        except PWTimeoutError:
            raise RuntimeError("Timeout saat membuka Shopee.")
        finally:
            context.close()

    rows = parse_products(html, limit=limit)

    if not rows:
        url_lower = (final_url or "").lower()
        html_lower = (html or "").lower()

        if _is_login_url(url_lower):
            raise RuntimeError("Shopee masih mengembalikan halaman login, bukan hasil pencarian.")
        if _is_captcha_url(url_lower):
            raise RuntimeError("Shopee masih mengembalikan halaman captcha, bukan hasil pencarian.")
        if "captcha" in html_lower or "anti_bot" in html_lower:
            raise RuntimeError("HTML yang diterima masih mengandung anti-bot/captcha Shopee.")

        raise RuntimeError(
            "Halaman Shopee berhasil dibuka, tetapi produk tidak terdeteksi parser. "
            "Cek runtime/debug_shopee.html untuk melihat DOM terbaru Shopee."
        )

    now = dt.datetime.now().isoformat(timespec="seconds")
    for r in rows:
        r.setdefault("source", "Shopee")
        r.setdefault("scraped_at", now)
        if keyword:
            r.setdefault("keyword", keyword)

    print(f"[Shopee] Berhasil parse {len(rows)} produk. (Mode 1 - visible)")
    return rows
