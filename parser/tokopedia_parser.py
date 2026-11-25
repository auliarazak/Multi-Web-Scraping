import re
import datetime as dt
from typing import List, Dict
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def format_rupiah(num: str) -> str:
    if not num:
        return ""
    try:
        n = int(re.sub(r"[^\d]", "", num))
        return "Rp" + f"{n:,}".replace(",", ".")
    except Exception:
        return ""


def parse_price_digits(text: str) -> str:
    text = clean(text)
    m = re.search(r"Rp\s*([\d\.]+)", text, flags=re.I)
    return m.group(1).replace(".", "") if m else ""


def is_product_url(url: str) -> bool:
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
        if any(low.startswith(x) for x in blocked):
            return False

        return True
    except Exception:
        return False


def _is_valid_rating_text(text: str) -> bool:
    if not text:
        return False

    t = clean(text).replace(",", ".")
    if not re.fullmatch(r"[0-5](?:\.\d)?", t):
        return False

    try:
        val = float(t)
        return 0.0 <= val <= 5.0
    except Exception:
        return False


def parse_rating_from_card(card) -> str:
    selector_candidates = [
        "span._2NfJxPu4JC-55aCJ8bEsyw==",
        "span[class*='rating']",
        "span",
    ]

    for sel in selector_candidates:
        try:
            spans = card.select(sel)
        except Exception:
            continue
        for s in spans:
            txt = clean(s.get_text(" ", strip=True))
            if _is_valid_rating_text(txt):
                return txt

    block = clean(card.get_text(" ", strip=True)).replace(",", ".")
    matches = re.findall(r"\b([0-5](?:\.\d)?)\b", block)
    for m in matches:
        if _is_valid_rating_text(m):
            return m

    return ""


def _extract_title(card) -> str:
    bad_words = (
        "hemat",
        "pakai bonus",
        "bisa cod",
        "official",
        "store",
        "shop",
        "terjual",
        "rp",
    )

    preferred = [
        'span[data-testid="spnSRPProdName"]',
        "span.+tnoqZhn89+NHUA43BpiJg==",
        "div.SzILjt4fxHUFNVT48ZPhHA== span",
    ]

    for sel in preferred:
        try:
            node = card.select_one(sel)
            if node:
                txt = clean(node.get_text(" ", strip=True))
                if len(txt) >= 8:
                    return txt
        except Exception:
            pass

    candidates = []
    for s in card.select("span"):
        txt = clean(s.get_text(" ", strip=True))
        if not txt:
            continue

        low = txt.lower()
        if any(b in low for b in bad_words):
            continue

        if _is_valid_rating_text(txt):
            continue

        if len(txt) >= 8:
            candidates.append(txt)

    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]

    texts = [clean(x) for x in card.stripped_strings]
    texts = [
        x for x in texts
        if len(x) >= 8
        and "rp" not in x.lower()
        and "terjual" not in x.lower()
    ]
    if texts:
        texts.sort(key=len, reverse=True)
        return texts[0]

    return ""


def _extract_shop_from_url(full_url: str) -> str:
    try:
        path = urlparse(full_url).path.strip("/")
        segs = [x for x in path.split("/") if x]
        if len(segs) >= 2:
            return segs[0]
    except Exception:
        pass
    return ""


def parse_products_from_html(html: str, base_url: str, limit: int = 100) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    rows: List[Dict[str, str]] = []
    seen = set()

    anchors = soup.select("div[data-testid='divSRPContentProducts'] a[href]")

    for a in anchors:
        if len(rows) >= limit:
            break

        href = sanitize_url(a.get("href", ""))
        full_url = urljoin(base_url, href)

        if not is_product_url(full_url):
            continue

        if full_url in seen:
            continue

        card = a
        chosen = None
        for _ in range(8):
            if card is None:
                break
            txt = clean(card.get_text(" ", strip=True))
            if len(txt) >= 40 and "Rp" in txt:
                chosen = card
                break
            card = getattr(card, "parent", None)

        card = chosen if chosen is not None else a

        block = clean(card.get_text(" ", strip=True))

        title = _extract_title(card)
        harga_digits = parse_price_digits(block)
        harga = format_rupiah(harga_digits)
        rating = parse_rating_from_card(card)
        toko = _extract_shop_from_url(full_url)

        if not title or not harga:
            continue

        rows.append({
            "source": "Tokopedia",
            "title": title,
            "harga": harga,
            "rating": rating,
            "toko": toko,
            "url": full_url,
            "scraped_at": now_iso(),
        })

        seen.add(full_url)

    return rows


def sanitize_url(url: str) -> str:
    return (url or "").split("?")[0].strip()