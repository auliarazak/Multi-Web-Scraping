import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


SCHEMAS = {
    "Shopee": ("source", "keyword", "title", "harga", "rating", "comment", "url"),
    "Tokopedia": ("source", "keyword", "title", "harga", "rating", "url"),
    "Lazada": ("source", "keyword", "title", "harga", "rating", "sold", "url"),
    "Google Research": ("source", "keyword", "title", "authors", "year", "abstract", "url"),
    "Google Reviews": ("source", "keyword", "title", "category", "price_range",
                       "review_count", "rating", "address", "country", "city", "url"),
    "News": ("source", "keyword", "title", "published", "comment", "url"),
}

COLUMNS = {
    "source": ("Sumber", 116), "keyword": ("Kata kunci", 116),
    "title": ("Judul", 220), "harga": ("Harga", 112), "rating": ("Rating", 82),
    "sold": ("Terjual", 96), "category": ("Kategori", 130),
    "price_range": ("Rentang harga", 140), "review_count": ("Jumlah ulasan", 132),
    "address": ("Alamat", 210), "country": ("Negara", 110), "city": ("Kota", 110),
    "authors": ("Penulis", 170), "year": ("Tahun", 84), "abstract": ("Abstrak", 260),
    "published": ("Tanggal terbit", 175), "comment": ("Komentar", 215), "url": ("URL", 200),
}


def columns_for(market):
    columns = []
    for key in SCHEMAS[market]:
        label, width = COLUMNS[key]
        if market == "Google Reviews" and key == "title":
            label = "Nama tempat"
        elif market == "News" and key == "comment":
            label = "Ringkasan"
        columns.append({"key": key, "label": label, "minWidth": width})
    return columns


_NUMBER = re.compile(r"(\d+(?:[.,]\d+)*)\s*(ribu|juta|rb|jt|k|m)?\b", re.I)
_SCALE = {"k": 1000, "rb": 1000, "ribu": 1000, "m": 1_000_000,
          "jt": 1_000_000, "juta": 1_000_000}


def _sort_value(key, text):
    if key in ("harga", "rating", "sold", "review_count", "year"):
        match = _NUMBER.search(text)
        if match:
            number, suffix = match.groups()
            if key != "rating" and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+(?:,\d{1,2})?", number):
                number = re.sub(r"[.,](?=\d{3}(?:[.,]|$))", "", number)
            try:
                return (0, float(number.replace(",", ".")) * _SCALE.get((suffix or "").casefold(), 1))
            except ValueError:
                pass
    elif key == "published":
        try:
            try:
                date = datetime.fromisoformat(text)
            except ValueError:
                date = parsedate_to_datetime(text)
            return (0, (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp())
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    return (1, text.casefold())


def visible_rows(rows, market, query, sort_key, descending):
    keys = SCHEMAS[market]
    query = query.strip().casefold()
    if query:
        rows = [row for row in rows if any(query in str(row.get(k, "")).casefold() for k in keys)]
    if sort_key not in keys:
        return rows
    present, missing = [], []
    for row in rows:
        raw = row.get(sort_key)
        value = "" if raw is None else str(raw).strip()
        if value in ("", "-", "—"):
            missing.append(row)
        else:
            present.append((_sort_value(sort_key, value), row))
    present.sort(key=lambda pair: pair[0], reverse=descending)
    return [row for _, row in present] + missing
