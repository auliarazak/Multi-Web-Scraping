import re
from bs4 import BeautifulSoup
from scrapy.selector import Selector
from urllib.parse import urljoin

_DIGIT_RE = re.compile(r"[\d\.]+")

def _parse_price_num(text: str):
    if not text:
        return None
    nums = _DIGIT_RE.findall(text.replace(",", "."))
    if not nums:
        return None
    try:
        return float(nums[0].replace(".", ""))
    except Exception:
        return None

def parse_products(html: str, limit: int = 100):
    sel = Selector(text=html)
    rows = []
    cards = sel.xpath("//div[contains(@class,'shopee-search-item-result__item')]")
    count = 0

    for card in cards:
        if count >= limit:
            break
        title = card.xpath(".//div[contains(@class,'ie3A+n') or contains(@class,'Cve6sh')]/text()").get()
        if not title:
            texts = [t.strip() for t in card.xpath(".//text()").getall() if t and t.strip()]
            title = max(texts, key=len) if texts else None

        href = card.xpath(".//a/@href").get()
        url = urljoin("https://shopee.co.id", href) if href else None

        image = card.xpath(".//img/@src").get() or card.xpath(".//img/@data-src").get()

        price_text = None
        for t in card.xpath(".//span/text()").getall():
            st = t.strip()
            if not st:
                continue
            if st.startswith("Rp") or _DIGIT_RE.search(st):
                price_text = st
                break
        price_num = _parse_price_num(price_text)

        sold_text = card.xpath(".//*[contains(text(),'Terjual')]/text()").get()
        location = card.xpath(".//div[contains(@class,'zGGwiV')]/text()").get()

        if not (title and url):
            continue

        rows.append({
            "source": "Shopee",
            "product_id": None,
            "title": title.strip(),
            "price_text": price_text,
            "price_num": price_num,
            "rating": None,
            "sold_text": sold_text.strip() if sold_text else None,
            "sold_num": None,
            "shop_name": None,
            "location": location.strip() if location else None,
            "url": url,
            "image": image
        })
        count += 1

    if not rows:
        soup = BeautifulSoup(html, "lxml")
        base = "https://shopee.co.id"
        for c in soup.select("div.shopee-search-item-result__item")[:limit]:
            title = None
            t1 = c.select_one("div.ie3A+n")
            t2 = c.select_one("div.Cve6sh")
            if t1: title = t1.get_text(strip=True)
            if not title and t2: title = t2.get_text(strip=True)
            a = c.find("a")
            url = urljoin(base, a["href"]) if a and a.has_attr("href") else None
            img = c.find("img")
            image = img.get("src") if img else None
            price_el = c.select_one("span.ZEgDH9") or c.find("span")
            price_text = price_el.get_text(strip=True) if price_el else None
            sold_el = c.find(string=lambda s: s and "Terjual" in s)
            loc_el = c.select_one("div.zGGwiV")
            location = loc_el.get_text(strip=True) if loc_el else None
            if not (title and url):
                continue
            rows.append({
                "source":"Shopee",
                "product_id": None,
                "title": title,
                "price_text": price_text,
                "price_num": _parse_price_num(price_text),
                "rating": None,
                "sold_text": sold_el.strip() if sold_el else None,
                "sold_num": None,
                "shop_name": None,
                "location": location,
                "url": url,
                "image": image
            })
    return rows
