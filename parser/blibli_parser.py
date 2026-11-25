import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def _clean(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _is_product_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    if "blibli.com" not in u:
        return False
    return ("/p/" in u) or ("ps--" in u)


def _extract_price_from_text(text: str) -> str:
    if not text:
        return ""
    cands = re.findall(r"Rp\s*[\d\.]+", text)
    if not cands:
        return ""

    def to_int(p):
        x = p.lower().replace("rp", "").replace(" ", "").replace(".", "")
        try:
            return int(x)
        except:
            return 0

    cands = sorted(set(cands), key=to_int, reverse=True)
    return _clean(cands[0])


def _keyword_tokens(keyword: str):
    if not keyword:
        return []
    tokens = re.split(r"[^a-z0-9]+", keyword.lower().strip())
    return [t for t in tokens if len(t) > 2]


def _is_relevant(title: str, keyword: str, strict: bool = False) -> bool:
    if not keyword:
        return True
    title_l = (title or "").lower()
    tokens = _keyword_tokens(keyword)
    if not tokens:
        return True
    return all(t in title_l for t in tokens) if strict else any(t in title_l for t in tokens)


def parse_products(html: str, base_url: str, limit: int = 60, keyword: str = "", strict_filter: bool = False):
    soup = BeautifulSoup(html, "html.parser")

    rows = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        full = urljoin(base_url, href)

        if not _is_product_url(full):
            continue
        if full in seen:
            continue

        card = a
        for _ in range(8):
            if not card or not getattr(card, "parent", None):
                break
            card = card.parent

        title = a.get("aria-label") or a.get("title") or a.get_text(" ", strip=True)
        title = _clean(title)
        if not title or len(title) < 5:
            continue

        if not _is_relevant(title, keyword, strict=strict_filter):
            continue

        price = ""

        price_selectors = [
            '[class*="product__price"]',
            '[class*="ProductPrice"]',
            '[class*="price"]',
            'span[class*="price"]',
            'div[class*="price"]',
        ]

        if card:
            for sel in price_selectors:
                el = card.select_one(sel)
                if el:
                    txt = _clean(el.get_text(" ", strip=True))
                    if "Rp" in txt:
                        price = _extract_price_from_text(txt)
                        if price:
                            break

        if not price and card:
            blob = _clean(card.get_text(" ", strip=True))
            price = _extract_price_from_text(blob)

        rating = ""
        reviews = ""
        sold = ""

        if card:
            blob = _clean(card.get_text(" ", strip=True))

            mr = re.search(r"\b([0-5](?:[.,]\d)?)\b", blob)
            if mr:
                rating = mr.group(1).replace(",", ".")

            mrev = re.search(r"\b(\d{1,5})\s*(ulasan|review|reviews)\b", blob.lower())
            if mrev:
                reviews = mrev.group(1)

            msold = re.search(r"\bterjual\s+([\d\.,]+[a-zA-Z]*)\b", blob.lower())
            if msold:
                sold = msold.group(1)

        meta = []
        if rating:
            meta.append(f"rating={rating}")
        if reviews:
            meta.append(f"reviews={reviews}")
        if sold:
            meta.append(f"sold={sold}")

        seen.add(full)
        rows.append({
            "source": "Blibli",
            "title": title[:180],
            "Price/Star": price,
            "comment": " | ".join(meta) if meta else "(metadata tidak tersedia)",
            "url": full
        })

        if len(rows) >= limit:
            break

    return rows
