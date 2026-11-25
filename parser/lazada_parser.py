import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def _clean(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _is_product_url(href: str) -> bool:
    if not href:
        return False
    h = href.lower()
    if h.startswith("//"):
        h = "https:" + h
    return ("/products/" in h) or bool(re.search(r"i\d+-s\d+", h))


def _extract_price_from_text(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    m = re.search(r"(rp\s*[\d\.]+)", t)
    if not m:
        return ""
    return _clean(m.group(1).replace("rp", "Rp"))


def _extract_rating_from_card(card) -> str:
    blob = _clean(card.get_text(" ", strip=True))
    m = re.search(r"\b([0-5](?:[.,]\d)?)\b", blob)
    if m:
        return m.group(1).replace(",", ".")
    return ""


def _keyword_tokens(keyword: str):
    if not keyword:
        return []
    kw = keyword.lower().strip()
    tokens = re.split(r"[^a-z0-9]+", kw)
    tokens = [t for t in tokens if len(t) > 2]
    return tokens


def _is_relevant(title: str, keyword: str, strict: bool = False) -> bool:
    if not keyword:
        return True
    title_l = (title or "").lower()
    tokens = _keyword_tokens(keyword)
    if not tokens:
        return True
    if strict:
        return all(t in title_l for t in tokens)
    return any(t in title_l for t in tokens)


def parse_products(html: str, base_url: str, limit: int = 100, keyword: str = "", strict_filter: bool = False):
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select('div[data-qa-locator="product-item"]')

    if not cards:
        anchors = soup.select('a[href*="/products/"]')
        seen_cards = set()
        for a in anchors:
            node = a
            for _ in range(4):
                if not node or not getattr(node, "parent", None):
                    break
                node = node.parent
            if node and id(node) not in seen_cards:
                seen_cards.add(id(node))
                cards.append(node)

    rows = []
    seen_url = set()

    for card in cards:
        if len(rows) >= limit:
            break

        a = card.select_one('a[href*="/products/"], a[href*="i"][href*="-s"]')
        if not a:
            continue

        href = a.get("href") or ""
        full_url = urljoin(base_url, href)
        if not _is_product_url(full_url):
            continue
        if full_url in seen_url:
            continue

        title = ""
        img = card.select_one("img[alt]")
        if img and img.get("alt"):
            title = img.get("alt")
        if not title and a.get("title"):
            title = a.get("title")
        if not title:
            title = a.get_text(" ", strip=True)

        title = _clean(title)
        if not title or len(title) < 5:
            continue

        if not _is_relevant(title, keyword, strict=strict_filter):
            continue

        seen_url.add(full_url)

        card_text = _clean(card.get_text(" ", strip=True))
        price = _extract_price_from_text(card_text)

        rating = _extract_rating_from_card(card)
        comment = f"rating={rating}" if rating else "(metadata tidak tersedia)"

        rows.append({
            "source": "Lazada",
            "title": title[:180],
            "Price/Star": price,
            "comment": comment,
            "url": full_url
        })

    return rows
