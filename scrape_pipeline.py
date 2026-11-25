from storage import (default_ttl_hours, get_cached_rows, get_cached_rows_by_url,
                     reviews_cache_keyword, save_rows_to_db, update_cache)


def run_pipeline(market, mode, keyword, limit, force_refresh, location,
                 scrape, normalize, display, storage_row):
    cache_keyword = (reviews_cache_keyword(keyword, location)
                     if market == "Google Reviews" and mode == "keyword"
                     else keyword)
    cached_rows = []
    if not force_refresh:
        if mode == "url":
            cached, fresh = get_cached_rows_by_url(
                keyword, ttl_hours=default_ttl_hours(market))
        else:
            cached, fresh = get_cached_rows(market, cache_keyword)
        if fresh and cached:
            cached_rows = [display(market, cache_keyword, row) for row in cached]
            if mode == "url" or len(cached_rows) >= limit:
                return cached_rows[:limit], "database"

    try:
        raw = scrape()
    except Exception:
        if cached_rows:
            return cached_rows, "database"
        raise

    normalized = [normalize(market, cache_keyword, row) for row in (raw or [])]
    displayed = [display(market, cache_keyword, row) for row in normalized]
    clean = [storage_row(row) for row in normalized if row.get("url")]
    if clean:
        save_rows_to_db(clean)

    if cached_rows:
        urls = {str(row.get("url") or "").strip().lower() for row in cached_rows}
        new_rows = [row for row in displayed
                    if str(row.get("url") or "").strip().lower() not in urls]
        merged = cached_rows + new_rows[:limit - len(cached_rows)]
        if clean:
            update_cache(market, cache_keyword, row_count=len(merged))
        return merged, "web"
    if clean:
        update_cache(market, cache_keyword, row_count=len(clean))
    return displayed, "web"
