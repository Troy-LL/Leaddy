"""Company site enrichment via Scrapling MCP bulk_fetch + parser."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from scrapling.parser import Selector

from .mcp_client import bulk_fetch, get_page

CONTACT_PATHS = ("/about", "/team", "/contact", "/about-us", "/company")


def _normalize_url(base: str, path: str) -> str:
    if path.startswith("http"):
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def _extract_leads_from_html(html: str, base_url: str) -> list[dict[str, Any]]:
    if not html:
        return []
    page = Selector(html)
    leads: list[dict[str, Any]] = []
    seen_emails: set[str] = set()

    for mailto in page.css("a[href^='mailto:']::attr(href)"):
        href = mailto.get() if hasattr(mailto, "get") else str(mailto)
        email = href.replace("mailto:", "").split("?")[0].strip().lower()
        if email and email not in seen_emails:
            seen_emails.add(email)
            leads.append(
                {"email": email, "url": base_url, "source": "company", "company": _host_name(base_url)}
            )

    for text in page.css("::text").getall():
        for match in re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text or ""):
            em = match.lower()
            if em not in seen_emails:
                seen_emails.add(em)
                leads.append(
                    {"email": em, "url": base_url, "source": "company", "company": _host_name(base_url)}
                )

    for name_el in page.css(
        ".team-member h3, .team-member h4, .person-name, .member-name, "
        "[class*='team'] h3, [class*='staff'] h3"
    ):
        name = name_el.css("::text").get()
        if name and len(name.strip()) > 2:
            leads.append(
                {
                    "name": name.strip(),
                    "url": base_url,
                    "source": "company",
                    "company": _host_name(base_url),
                }
            )

    return leads


def _host_name(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


async def scrape_company_urls(urls: list[str], *, max_urls: int = 15) -> list[dict[str, Any]]:
    targets: list[str] = []
    for base in urls[:max_urls]:
        if not base or not base.startswith("http"):
            continue
        parsed = urlparse(base)
        root = f"{parsed.scheme}://{parsed.netloc}"
        targets.append(base)
        for path in CONTACT_PATHS:
            targets.append(_normalize_url(root, path))

    targets = list(dict.fromkeys(targets))[: max_urls * 4]
    if not targets:
        return []

    all_leads: list[dict[str, Any]] = []
    mcp_results = await bulk_fetch(
        targets,
        css_selector="a[href^='mailto'], h3, .team-member, .person-name",
    )

    if mcp_results:
        for item in mcp_results:
            url = item.get("url") or item.get("source_url") or ""
            html = item.get("content") or item.get("html") or item.get("markdown") or ""
            if isinstance(html, dict):
                html = html.get("text", "") or str(html)
            all_leads.extend(_extract_leads_from_html(str(html), url or targets[0]))
    else:
        for url in targets[:10]:
            page_data = await get_page(url)
            html = page_data.get("content") or page_data.get("html") or ""
            if not html:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        r = await client.get(
                            url,
                            headers={"User-Agent": "Mozilla/5.0"},
                            follow_redirects=True,
                        )
                        html = r.text
                except Exception:
                    continue
            all_leads.extend(_extract_leads_from_html(str(html), url))

    return all_leads
