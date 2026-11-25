import time
import datetime as dt
import re
import random
from urllib.parse import quote_plus, urlparse, urljoin

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from .driver import build_driver


def build_search_url(keyword: str, page: int = 1) -> str:
    url = f"https://www.lazada.co.id/catalog/?q={quote_plus(keyword)}"
    if page and int(page) > 1:
        url += f"&page={int(page)}"
    return url


def looks_like_search(url: str) -> bool:
    try:
        u = urlparse(url)
        return "lazada.co.id" in (u.netloc or "")
    except:
        return False


def _txt(el):
    try:
        return (el.text or "").strip()
    except:
        return ""


def _attr(el, name):
    try:
        return (el.get_attribute(name) or "").strip()
    except:
        return ""


def _normalize(base, href):
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    return urljoin(base, href)


def _scroll_rounds_for_limit(limit, scroll_rounds=None):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 60
    derived = max(8, (limit + 3) // 4)
    if scroll_rounds:
        try:
            derived = max(derived, int(scroll_rounds))
        except (TypeError, ValueError):
            pass
    return min(derived, 25)


def _human_scroll(driver, rounds=8, stop_event=None, limit=None,
                  wait=1.2):
    target = int(limit) if limit else 0
    no_new = 0
    last_count = len(_collect_cards(driver))
    for _ in range(rounds):
        if stop_event is not None and stop_event.is_set():
            break

        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )

        time.sleep(wait + random.uniform(0.3, 0.9))

        count = len(_collect_cards(driver))
        if target and count >= target:
            break
        if count <= last_count:
            no_new += 1
            if no_new >= 3:
                break
        else:
            no_new = 0
        last_count = count


def _collect_cards(driver):

    cards = driver.find_elements(By.CSS_SELECTOR, "div.buTCk")

    if cards:
        return cards

    cards = driver.find_elements(By.CSS_SELECTOR, '[data-qa-locator="product-item"]')

    return cards


def _parse_cards(driver, limit, now, seen, items):
    base = driver.current_url
    cards = _collect_cards(driver)
    added = 0
    for card in cards:
        if len(items) >= limit:
            break
        try:
            a = card.find_element(By.CSS_SELECTOR, 'a[href*="/products/"]')
        except Exception:
            continue
        href = _attr(a, "href")
        url = _normalize(base, href)
        if not url or url in seen:
            continue
        seen.add(url)
        title = _attr(a, "title") or _txt(a)
        price = ""
        try:
            price = _txt(card.find_element(By.CSS_SELECTOR, "span.ooOxS"))
        except Exception:
            pass
        sold = ""
        try:
            sold = _txt(card.find_element(By.CSS_SELECTOR, "span._1cEkb"))
        except Exception:
            pass
        rating = ""
        try:
            stars = card.find_elements(By.CSS_SELECTOR, "i._9-ogB.Dy1nx")
            if stars:
                rating = str(len(stars))
        except Exception:
            pass
        items.append(
            {
                "source": "Lazada",
                "title": title,
                "harga": price,
                "rating": rating,
                "sold": sold,
                "url": url,
                "scraped_at": now,
            }
        )
        added += 1
    return added


def scrape_lazada(
    keyword=None,
    url=None,
    headless=False,
    limit=60,
    scroll_rounds=8,
    wait=1.2,
    stop_event=None,
):

    if keyword and not url:
        target = build_search_url(keyword)
    elif url:
        if not looks_like_search(url):
            raise ValueError("URL harus halaman Lazada")
        target = url
    else:
        raise ValueError("Masukkan keyword / URL")

    driver = build_driver(headless=headless)
    now = dt.datetime.now().isoformat(timespec="seconds")

    try:
        driver.get(target)

        WebDriverWait(driver, 30).until(
            lambda d: len(_collect_cards(d)) > 0
        )

        time.sleep(2)

        _human_scroll(driver, _scroll_rounds_for_limit(limit, scroll_rounds),
                      stop_event=stop_event, limit=limit, wait=wait)

        items = []
        seen = set()
        _parse_cards(driver, limit, now, seen, items)
        if keyword and not url and len(items) < limit:
            max_pages = 10
            for page in range(2, max_pages + 1):
                if len(items) >= limit:
                    break
                if stop_event is not None and stop_event.is_set():
                    break
                driver.get(build_search_url(keyword, page=page))
                try:
                    WebDriverWait(driver, 30).until(
                        lambda d: len(_collect_cards(d)) > 0
                    )
                except TimeoutException:
                    break
                time.sleep(2)
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                time.sleep(wait)
                added = _parse_cards(driver, limit, now, seen, items)
                if added == 0:
                    break

        return items

    finally:
        driver.quit()