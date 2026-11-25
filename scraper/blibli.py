import time
import datetime as dt
from urllib.parse import quote_plus, urlparse, urljoin

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .driver import build_driver


def build_search_url(keyword: str) -> str:
    return f"https://www.blibli.com/jual/{quote_plus(keyword)}"


def looks_like_search(url: str) -> bool:
    try:
        u = urlparse(url)
        return ("blibli.com" in u.netloc) and ("/jual/" in u.path or "/search" in u.path)
    except Exception:
        return False


def _clean(s: str) -> str:
    return " ".join((s or "").split()).strip()


def _abs_url(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base, href)


def scrape_blibli_with_reviews(
    keyword: str = None,
    url: str = None,
    headless: bool = True,
    limit: int = 60,
    limit_products: int = 10,
    reviews_per_product: int = 2,
    scroll_rounds_search: int = 10,
    scroll_rounds_reviews: int = 6,
    wait: float = 1.3,
):
    

    if keyword and not url:
        target = build_search_url(keyword)
    elif url:
        target = url
    else:
        raise ValueError("Masukkan keyword atau URL Blibli search.")

    driver = build_driver(headless=headless)
    now = dt.datetime.now().isoformat(timespec="seconds")

    try:
        driver.get(target)
        time.sleep(3.5)

        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="ps--"]'))
        )

        last = 0
        stagnant = 0
        for _ in range(max(4, scroll_rounds_search)):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(wait)
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="ps--"]')
            if len(links) <= last:
                stagnant += 1
            else:
                stagnant = 0
                last = len(links)
            if len(links) >= limit_products * 3:
                break
            if stagnant >= 3:
                break

        base_url = driver.current_url
        anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="ps--"]')

        products = []
        seen = set()
        for a in anchors:
            if len(products) >= limit_products:
                break

            href = (a.get_attribute("href") or "").strip()
            full = _abs_url(base_url, href)
            if not full or full in seen:
                continue

            title = (a.get_attribute("aria-label") or a.get_attribute("title") or "").strip()
            if not title:
                title = _clean(a.text)

            title = _clean(title)
            if not title or len(title) < 5:
                continue

            seen.add(full)
            products.append({"title": title[:180], "url": full})

        rows = []
        for p in products:
            if len(rows) >= limit:
                break

            prod_url = p["url"]
            prod_title = p["title"]

            try:
                driver.get(prod_url)
                time.sleep(3.5)
            except Exception:
                continue

     
            for _ in range(max(1, scroll_rounds_reviews)):
                driver.execute_script("window.scrollBy(0, 900);")
                time.sleep(wait)

            blocks = driver.find_elements(By.CSS_SELECTOR, "div, p, span")
            taken = 0

            for b in blocks:
                if taken >= reviews_per_product:
                    break

                txt = _clean(b.text)
                if len(txt) < 20:
                    continue

                low = txt.lower()
                if "lebih murah di app" in low or "download aplikasinya" in low:
                    continue
                if "syarat" in low and "ketentuan" in low:
                    continue

                rows.append({
                    "source": "Blibli Reviews",
                    "title": prod_title,
                    "Price/Star": "",      
                    "comment": txt[:350],
                    "url": prod_url,
                    "scraped_at": now
                })
                taken += 1

            if taken == 0:
                rows.append({
                    "source": "Blibli Reviews",
                    "title": prod_title,
                    "Price/Star": "",
                    "comment": "(review tidak tersedia / tidak terdeteksi)",
                    "url": prod_url,
                    "scraped_at": now
                })

        return rows

    finally:
        driver.quit()


def scrape_blibli(
    keyword: str = None,
    url: str = None,
    headless: bool = True,
    limit: int = 60,
    scroll_rounds: int = 10,
    wait: float = 1.3,
):

    limit_products = max(1, min(12, (limit + 1) // 2))
    return scrape_blibli_with_reviews(
        keyword=keyword,
        url=url,
        headless=headless,
        limit=limit,
        limit_products=limit_products,
        reviews_per_product=2,
        scroll_rounds_search=scroll_rounds,
        scroll_rounds_reviews=max(4, scroll_rounds // 2),
        wait=wait
    )