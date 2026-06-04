"""Google SERP discovery via HTTP + Scrapling parser."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote_plus

import httpx
from scrapling.parser import Selector

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def search_google(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    serp_key = os.getenv("GOOGLE_SERP_KEY", "").strip()
    if serp_key:
        return await _search_via_api(query, serp_key, limit=limit)
    return await _search_direct(query, limit=limit)


async def _search_via_api(query: str, api_key: str, *, limit: int) -> list[dict[str, Any]]:
    """Placeholder for paid SERP API — extend with SerpAPI/Bright Data as needed."""
    return await _search_direct(query, limit=limit)


async def _search_direct(query: str, *, limit: int) -> list[dict[str, Any]]:
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={limit}"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
    except Exception:
        return []

    page = Selector(html)
    results: list[dict[str, Any]] = []
    for block in page.css("div.g, div[data-sokoban-container]"):
        title_el = block.css("h3")
        if not title_el:
            continue
        title = title_el[0].css("::text").get() if title_el else None
        link_el = block.css("a::attr(href)")
        link = link_el.get() if link_el else None
        if not title or not link or link.startswith("/"):
            continue
        if "google.com" in link:
            continue
        snippet_el = block.css("div[data-sncf], span")
        snippet = None
        for s in snippet_el:
            text = s.css("::text").get()
            if text and len(text) > 20:
                snippet = text
                break
        results.append(
            {
                "company": title.strip(),
                "url": link,
                "snippet": snippet,
                "source": "google",
            }
        )
        if len(results) >= limit:
            break

    if not results:
        results = _fallback_link_extract(page, limit=limit)
    return results


def _fallback_link_extract(page: Selector, *, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for href in page.css("a::attr(href)"):
        link = href.get() if hasattr(href, "get") else str(href)
        if not link or not link.startswith("http"):
            continue
        if "google." in link or "gstatic" in link:
            continue
        host_match = re.search(r"https?://([^/]+)", link)
        company = host_match.group(1) if host_match else link
        results.append({"company": company, "url": link, "snippet": None, "source": "google"})
        if len(results) >= limit:
            break
    return results
