from __future__ import annotations

import os
import re
import datetime as dt
from urllib.parse import quote_plus, urlparse
from typing import Any, Dict, List, Optional

from playwright.sync_api import Error as PWError, sync_playwright, TimeoutError as PWTimeoutError

from parser.tokopedia_parser import parse_products_from_html
from config import RUNTIME_DIR


BASE = "https://www.tokopedia.com"


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def sanitize_url(url: str) -> str:
    if not url:
        return ""
    return url.split("?")[0].strip()


def is_tokopedia_product_url(url: str) -> bool:
    if not url:
        return False

    try:
        u = urlparse(url)
        if "tokopedia.com" not in (u.netloc or "").lower():
            return False

        path = (u.path or "").strip("/")
        if not path:
            return False

        segs = [x for x in path.split("/") if x]
        if len(segs) < 2:
            return False

        blocked = (
            "search",
            "promo",
            "discovery",
            "help",
            "blog",
            "about",
            "cart",
            "wishlist",
            "login",
            "register",
            "campaign",
            "hot",
            "find",
            "official-store",
            "people",
            "u",
            "p",
        )

        low = path.lower()
        if any(low.startswith(b) for b in blocked):
            return False

        return True
    except Exception:
        return False


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def get_by_candidates(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def find_nested_first(obj: Any, wanted_keys: List[str]) -> Any:
    if isinstance(obj, dict):
        for k in wanted_keys:
            if k in obj and obj[k] not in (None, "", [], {}):
                return obj[k]
        for v in obj.values():
            found = find_nested_first(v, wanted_keys)
            if found not in (None, "", [], {}):
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = find_nested_first(item, wanted_keys)
            if found not in (None, "", [], {}):
                return found

    return None


def looks_like_product_dict(d: Dict[str, Any]) -> bool:
    keys = {str(k).lower() for k in d.keys()}

    has_title_key = any(k in keys for k in [
        "name", "title", "product_name", "producttitle", "product_name_display"
    ])

    has_price_key = any(
        "price" in k or "original_price" in k or "discount_price" in k
        for k in keys
    )

    has_url_key = any(k in keys for k in ["url", "link", "product_url", "canonical_url"])

    return (has_title_key and has_price_key) or (has_title_key and has_url_key)


def flatten_product_candidates(obj: Any, out: List[Dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        if looks_like_product_dict(obj):
            out.append(obj)
        for v in obj.values():
            flatten_product_candidates(v, out)
    elif isinstance(obj, list):
        for item in obj:
            flatten_product_candidates(item, out)


def extract_url_from_obj(d: Dict[str, Any]) -> str:
    url = get_by_candidates(d, ["url", "link", "product_url", "canonical_url", "deeplink"])
    if isinstance(url, str) and is_tokopedia_product_url(url):
        return sanitize_url(url)

    found = find_nested_first(d, ["url", "link", "product_url", "canonical_url", "deeplink"])
    if isinstance(found, str) and is_tokopedia_product_url(found):
        return sanitize_url(found)

    return ""


def extract_title_from_obj(d: Dict[str, Any]) -> str:
    title = get_by_candidates(
        d,
        ["name", "title", "product_name", "productName", "product_name_display"]
    )
    if isinstance(title, str):
        return clean(title)

    found = find_nested_first(
        d,
        ["name", "title", "product_name", "productName", "product_name_display"]
    )
    return clean(found) if isinstance(found, str) else ""


def extract_price_from_obj(d: Dict[str, Any]) -> str:
    candidates = [
        "price",
        "final_price",
        "discount_price",
        "original_price",
        "min_price",
        "max_price",
        "price_text",
    ]

    val = get_by_candidates(d, candidates)
    if val is None:
        val = find_nested_first(d, candidates)

    if val is None:
        return ""

    if isinstance(val, (int, float)):
        n = int(val)
        return "Rp" + f"{n:,}".replace(",", ".")

    if isinstance(val, str):
        digits = re.sub(r"[^\d]", "", val)
        if digits:
            n = int(digits)
            return "Rp" + f"{n:,}".replace(",", ".")

    if isinstance(val, dict):
        for kk in ["value", "amount", "text", "display", "price"]:
            if kk in val:
                vv = val[kk]
                if isinstance(vv, (int, float)):
                    n = int(vv)
                    return "Rp" + f"{n:,}".replace(",", ".")
                if isinstance(vv, str):
                    digits = re.sub(r"[^\d]", "", vv)
                    if digits:
                        n = int(digits)
                        return "Rp" + f"{n:,}".replace(",", ".")

    return ""


def extract_rating_from_obj(d: Dict[str, Any]) -> str:
    candidates = ["rating", "average_rating", "avg_rating", "product_rating", "shop_rating"]
    val = get_by_candidates(d, candidates)
    if val is None:
        val = find_nested_first(d, candidates)

    if val is None:
        return ""

    if isinstance(val, (int, float)):
        f = float(val)
        if 0.0 <= f <= 5.0:
            s = f"{f:.1f}"
            return s[:-2] if s.endswith(".0") else s

    if isinstance(val, str):
        t = clean(val).replace(",", ".")
        if re.fullmatch(r"[0-5](?:\.\d)?", t):
            try:
                f = float(t)
                if 0.0 <= f <= 5.0:
                    return t
            except Exception:
                pass

    return ""


def extract_shop_from_obj(d: Dict[str, Any], url: str = "") -> str:
    candidates = [
        "shop_name",
        "shopName",
        "store_name",
        "storeName",
        "seller_name",
        "sellerName",
        "merchant_name",
        "shop",
    ]
    val = get_by_candidates(d, candidates)
    if val is None:
        val = find_nested_first(d, candidates)

    if isinstance(val, str) and clean(val):
        return clean(val)

    try:
        path = urlparse(url).path.strip("/")
        segs = [x for x in path.split("/") if x]
        if len(segs) >= 2:
            return segs[0]
    except Exception:
        pass

    return ""


def normalize_product_from_obj(d: Dict[str, Any]) -> Optional[Dict[str, str]]:
    url = extract_url_from_obj(d)
    title = extract_title_from_obj(d)
    harga = extract_price_from_obj(d)
    rating = extract_rating_from_obj(d)
    toko = extract_shop_from_obj(d, url)

    if not title:
        return None

    if not url or not is_tokopedia_product_url(url):
        return None

    if not harga:
        return None

    return {
        "source": "Tokopedia",
        "title": title,
        "harga": harga,
        "rating": rating,
        "toko": toko,
        "url": url,
        "scraped_at": now_iso(),
    }


def merge_rows(
    rows: List[Dict[str, str]],
    incoming: List[Dict[str, str]],
    seen_url: set,
    seen_key: set,
    limit: int
) -> None:
    for item in incoming:
        if len(rows) >= limit:
            return

        url = sanitize_url(item.get("url", ""))
        title = clean(item.get("title", ""))
        harga = clean(item.get("harga", ""))
        toko = clean(item.get("toko", ""))

        if not url or not title or not harga:
            continue

        if url in seen_url:
            continue

        dedup_key = (title.lower(), harga, toko.lower())
        if dedup_key in seen_key:
            continue

        item["url"] = url
        item["title"] = title
        item["harga"] = harga
        item["toko"] = toko
        if "scraped_at" not in item or not item["scraped_at"]:
            item["scraped_at"] = now_iso()
        item["source"] = "Tokopedia"

        rows.append(item)
        seen_url.add(url)
        seen_key.add(dedup_key)


def _max_scroll_for_limit(limit: int, scroll_rounds=None,
                          max_scroll=None) -> int:
    derived = (int(limit or 20) + 4) // 5 + 3
    derived = max(5, min(25, derived))
    if max_scroll is not None:
        return max(1, min(25, int(max_scroll)))
    if scroll_rounds is not None:
        return max(derived, min(25, int(scroll_rounds)))
    return derived


def _page_height(page):
    try:
        return int(page.evaluate("document.body.scrollHeight"))
    except Exception:
        return None


class _NavigationConnectionError(ConnectionError):
    """Koneksi ke halaman pencarian gagal juga pada percobaan kedua."""


def _open_search(page, target, stop_event):
    for attempt in range(2):
        try:
            page.goto(target, timeout=60000, wait_until="domcontentloaded")
            return True
        except PWTimeoutError:
            return True
        except PWError as exc:
            if "net::ERR_HTTP2_PROTOCOL_ERROR" not in str(exc):
                raise
            if attempt:
                raise _NavigationConnectionError(
                    "Koneksi HTTP/2 ke Tokopedia gagal dua kali "
                    "(ERR_HTTP2_PROTOCOL_ERROR).") from exc
            if stop_event is not None:
                if stop_event.wait(1):
                    return False
            else:
                page.wait_for_timeout(1000)


def _scrape_tokopedia_single(
    keyword: Optional[str] = None,
    url: Optional[str] = None,
    headless: bool = True,
    limit: int = 20,
    sort: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    max_scroll=None,
    scroll_rounds=None,
    wait: float = 1.4,
    on_progress=None,
    on_partial=None,
    stop_event=None,
    **kwargs
) -> List[Dict[str, str]]:
    if keyword and not url:
        target = f"{BASE}/search?st=product&q={quote_plus(keyword)}"
        if sort is not None:
            target += f"&sort={int(sort)}"
        if price_min is not None:
            target += f"&pmin={int(price_min)}"
        if price_max is not None:
            target += f"&pmax={int(price_max)}"
    elif url:
        target = url
    else:
        raise ValueError("Keyword atau URL wajib")

    rows: List[Dict[str, str]] = []
    seen_url = set()
    seen_key = set()
    intercepted_pool: List[Dict[str, str]] = []
    if scroll_rounds is None:
        scroll_rounds = kwargs.get("scroll_rounds")
    if on_progress is None:
        on_progress = kwargs.get("on_progress")
    if on_partial is None:
        on_partial = kwargs.get("on_partial")
    if stop_event is None:
        stop_event = kwargs.get("stop_event")
    effective_max_scroll = _max_scroll_for_limit(
        limit, scroll_rounds=scroll_rounds, max_scroll=max_scroll)

    def _emit_progress(round_no: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(len(rows), int(limit), int(round_no), list(rows))
        except TypeError:
            try:
                on_progress(len(rows), int(limit), int(round_no))
            except Exception:
                pass
        except Exception:
            pass

    def _emit_partial(exc: Exception) -> None:
        if on_partial is None:
            return
        try:
            on_partial(str(exc), len(rows))
        except TypeError:
            try:
                on_partial(str(exc))
            except Exception:
                pass
        except Exception:
            pass

    _log_path = os.path.join(RUNTIME_DIR, "tokopedia_debug.log")

    def _log(msg: str) -> None:
        try:
            os.makedirs(RUNTIME_DIR, exist_ok=True)
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(f"{dt.datetime.now().strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def _dom_card_count() -> int:
        try:
            return int(page.evaluate(
                "document.querySelectorAll("
                "\"div[data-testid='divSRPContentProducts'] a[href]\").length"))
        except Exception:
            return -1

    def _wait_for_new_content(timeout_ms: int = 4000) -> bool:
        before_pool = len(intercepted_pool)
        before_dom = _dom_card_count()
        waited = 0
        while waited < timeout_ms:
            if stop_event is not None and stop_event.is_set():
                return False
            page.wait_for_timeout(400)
            waited += 400
            if len(intercepted_pool) > before_pool:
                return True
            now_dom = _dom_card_count()
            if now_dom >= 0 and before_dom < 0:
                before_dom = now_dom
            elif now_dom > before_dom >= 0:
                return True
        return False

    def handle_response(resp) -> None:
        try:
            rtype = resp.request.resource_type
            if rtype not in ("xhr", "fetch"):
                return

            ctype = (resp.headers or {}).get("content-type", "").lower()
            resp_url = str(getattr(resp, "url", "?"))[:110]
            if "json" not in ctype:
                _log(f"xhr {resp_url} bukan-json ({ctype[:40]})")
                return

            data = resp.json()
            if not data:
                _log(f"xhr {resp_url} json-kosong")
                return

            candidates: List[Dict[str, Any]] = []
            flatten_product_candidates(data, candidates)

            normalized: List[Dict[str, str]] = []
            for c in candidates:
                item = normalize_product_from_obj(c)
                if item:
                    normalized.append(item)

            if normalized:
                intercepted_pool.extend(normalized)
            _log(f"xhr {resp_url} kandidat={len(candidates)} produk={len(normalized)}")

        except Exception:
            pass

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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="id-ID",
        )

        page = context.new_page()
        page.on("response", handle_response)

        try:
            if stop_event is not None and stop_event.is_set():
                return rows[:limit]
            if not _open_search(page, target, stop_event):
                return rows[:limit]

            try:
                page.wait_for_selector("div[data-testid='divSRPContentProducts']", timeout=15000)
            except PWTimeoutError:
                pass
            page.wait_for_timeout(3000)
            _emit_progress(0)

            band_tag = ""
            if price_min is not None or price_max is not None:
                band_tag = (f" pmin={price_min if price_min is not None else '-'}"
                            f" pmax={price_max if price_max is not None else '-'}")
            _log(f"=== run keyword={keyword or url or '?'} sort={sort if sort is not None else 'default'}{band_tag} limit={limit} ===")

            prev_height = _page_height(page)
            no_new_rounds = 0
            no_height_rounds = 0

            for round_no in range(1, effective_max_scroll + 1):
                if stop_event is not None and stop_event.is_set():
                    break
                before_len = len(rows)
                pool_before = len(intercepted_pool)

                if intercepted_pool:
                    merge_rows(rows, intercepted_pool, seen_url, seen_key, limit)
                    intercepted_pool.clear()

                if len(rows) >= limit:
                    break

                dom_found = 0
                try:
                    html = page.content()
                    dom_rows = parse_products_from_html(html=html, base_url=BASE, limit=limit)
                    dom_found = len(dom_rows)
                    merge_rows(rows, dom_rows, seen_url, seen_key, limit)
                except Exception:
                    pass

                _emit_progress(round_no)

                if len(rows) >= limit:
                    break
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                clicks_ok = 0
                clicks_fail = 0
                clicks_js = 0
                click_err = ""
                for _click in range(5):
                    try:
                        load_more = page.locator("button:has-text('Muat Lebih Banyak')")
                        if load_more.count() == 0 or not load_more.first.is_visible():
                            break
                        try:
                            load_more.first.click(timeout=3000)
                        except Exception:
                            page.evaluate(
                                "[...document.querySelectorAll('button')]"
                                ".find(b => b.textContent.includes('Muat Lebih Banyak'))?.click()")
                            clicks_js += 1
                        clicks_ok += 1
                        if not _wait_for_new_content(timeout_ms=4000):
                            break
                        if intercepted_pool:
                            merge_rows(rows, intercepted_pool, seen_url, seen_key, limit)
                            intercepted_pool.clear()
                        if len(rows) >= limit:
                            break
                    except Exception as exc:
                        clicks_fail += 1
                        click_err = str(exc).replace("\n", " ")[:100]
                        break

                try:
                    page.mouse.wheel(0, 12000)
                except Exception:
                    try:
                        page.evaluate("window.scrollBy(0, 12000)")
                    except Exception:
                        pass

                _wait_for_new_content(timeout_ms=2500)

                if intercepted_pool:
                    merge_rows(rows, intercepted_pool, seen_url, seen_key, limit)
                    intercepted_pool.clear()

                _emit_progress(round_no)
                if len(rows) == before_len:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0

                height = _page_height(page)
                if height is not None and prev_height is not None:
                    if height <= prev_height:
                        no_height_rounds += 1
                    else:
                        no_height_rounds = 0
                    prev_height = height

                try:
                    btn_count = page.locator("button:has-text('Muat Lebih Banyak')").count()
                except Exception:
                    btn_count = -1
                _log(f"ronde={round_no} rows={len(rows)} baru={len(rows) - before_len} "
                     f"dom={dom_found} pool={pool_before} tinggi={height} "
                     f"btn={btn_count} klik_ok={clicks_ok} klik_js={clicks_js} "
                     f"klik_gagal={clicks_fail} klik_err={click_err} "
                     f"no_new={no_new_rounds} no_height={no_height_rounds}")

                if len(rows) >= limit:
                    break

                if no_new_rounds >= 8 or no_height_rounds >= 5:
                    break

            if len(rows) >= limit:
                _log(f"STOP limit tercapai (rows={len(rows)})")
            elif stop_event is not None and stop_event.is_set():
                _log(f"STOP tombol Stop (rows={len(rows)})")
            elif no_new_rounds >= 8:
                _log(f"STOP stall: 8 ronde tanpa baris baru (rows={len(rows)})")
            elif no_height_rounds >= 5:
                _log(f"STOP stall: 5 ronde tanpa tinggi baru (rows={len(rows)})")
            else:
                _log(f"STOP cap ronde habis (rows={len(rows)})")

            return rows[:limit]
        except Exception as exc:
            if rows:
                _emit_partial(exc)
                return rows[:limit]
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


def _price_bands(rows: List[Dict[str, str]], n_bands: int = 4):
    prices = []
    for r in rows:
        digits = re.sub(r"[^\d]", "", r.get("harga", "") or "")
        if digits:
            try:
                prices.append(int(digits))
            except ValueError:
                pass
    prices.sort()
    if len(prices) < 8:
        return []
    if len(set(prices)) < 4:
        return []
    cuts = []
    for i in range(1, n_bands):
        cuts.append(prices[int(len(prices) * i / n_bands)])
    cuts = sorted(set(cuts))
    if not cuts:
        return []
    bands = []
    prev = None
    for c in cuts:
        bands.append((prev, c))
        prev = c
    bands.append((prev, None))
    return bands


_SORT_PASSES = [None, 3, 4, 9, 5]


def scrape_tokopedia(
    keyword: Optional[str] = None,
    url: Optional[str] = None,
    headless: bool = True,
    limit: int = 20,
    max_scroll=None,
    scroll_rounds=None,
    wait: float = 1.4,
    on_progress=None,
    on_partial=None,
    stop_event=None,
    **kwargs
) -> List[Dict[str, str]]:
    kwargs.pop("sort", None)
    kwargs.pop("price_min", None)
    kwargs.pop("price_max", None)
    if url or not keyword:
        return _scrape_tokopedia_single(
            keyword=keyword, url=url, headless=headless, limit=limit,
            max_scroll=max_scroll, scroll_rounds=scroll_rounds,
            wait=wait, on_progress=on_progress, on_partial=on_partial,
            stop_event=stop_event, **kwargs)

    all_rows: List[Dict[str, str]] = []
    seen_url = set()
    seen_key = set()

    def _progress_cum(found, lim, round_no, rows_snapshot=None):
        if on_progress is None:
            return
        cum_rows = list(all_rows)
        merge_rows(cum_rows, rows_snapshot or [],
                   set(seen_url), set(seen_key), lim)
        try:
            on_progress(len(cum_rows), int(lim),
                        int(round_no), cum_rows)
        except TypeError:
            try:
                on_progress(len(cum_rows), int(lim),
                            int(round_no))
            except Exception:
                pass
        except Exception:
            pass

    def _partial_cum(msg, found=None):
        if on_partial is None:
            return
        try:
            on_partial(msg, len(all_rows) + int(found or 0))
        except TypeError:
            try:
                on_partial(msg)
            except Exception:
                pass
        except Exception:
            pass

    last_exc = [None]
    connection_error = None

    def _run_pass(**single_kw):
        nonlocal connection_error
        try:
            rows = _scrape_tokopedia_single(
                keyword=keyword, headless=headless, limit=limit,
                max_scroll=max_scroll, scroll_rounds=scroll_rounds,
                wait=wait, on_progress=_progress_cum,
                on_partial=_partial_cum, stop_event=stop_event,
                **{**kwargs, **single_kw})
        except _NavigationConnectionError as exc:
            connection_error = exc
            return None
        except Exception as exc:
            last_exc[0] = exc
            return None
        before = len(all_rows)
        merge_rows(all_rows, rows, seen_url, seen_key, limit)
        return len(all_rows) - before

    def _stopped():
        return stop_event is not None and stop_event.is_set()

    zero_new_passes = 0
    for sort in _SORT_PASSES:
        if len(all_rows) >= limit or _stopped():
            break
        new = _run_pass(sort=sort)
        if connection_error:
            break
        if new is None:
            continue
        if new == 0:
            zero_new_passes += 1
            if zero_new_passes >= 2:
                break
        else:
            zero_new_passes = 0

    if not connection_error and len(all_rows) < limit and not _stopped():
        zero_new_passes = 0
        for pmin, pmax in _price_bands(all_rows):
            if len(all_rows) >= limit or _stopped():
                break
            new = _run_pass(price_min=pmin, price_max=pmax)
            if connection_error:
                break
            if new is None:
                continue
            if new == 0:
                zero_new_passes += 1
                if zero_new_passes >= 2:
                    break
            else:
                zero_new_passes = 0

    if connection_error:
        if not all_rows:
            raise connection_error
        _partial_cum(str(connection_error))
    if not all_rows and last_exc[0] is not None:
        raise last_exc[0]
    return all_rows[:limit]
