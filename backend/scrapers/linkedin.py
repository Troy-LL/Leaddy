"""LinkedIn profile enrichment via Scrapling MCP stealthy_fetch."""

from __future__ import annotations

import os
import re
from typing import Any

from scrapling.parser import Selector

from .mcp_client import stealthy_fetch


async def fetch_linkedin(profile_url: str) -> dict[str, Any]:
    li_at = os.getenv("LI_AT", "").strip()
    if not li_at:
        return {}

    if "linkedin.com" not in profile_url:
        return {}

    data = await stealthy_fetch(
        profile_url,
        cookies={"li_at": li_at},
        css_selector=".top-card-layout__title, .top-card-layout__headline, h1",
        headless=True,
    )

    html = ""
    if isinstance(data, dict):
        html = data.get("content") or data.get("html") or data.get("markdown") or ""
        if isinstance(html, dict):
            html = html.get("text", "") or str(html)
        if data.get("name") or data.get("title"):
            return {
                "name": data.get("name"),
                "title": data.get("title"),
                "url": profile_url,
                "source": "linkedin",
            }
    else:
        html = str(data)

    if not html:
        return {}

    page = Selector(html)
    name = (
        page.css(".top-card-layout__title::text").get()
        or page.css("h1::text").get()
        or page.css("[data-anonymize='person-name']::text").get()
    )
    title = (
        page.css(".top-card-layout__headline::text").get()
        or page.css(".text-body-medium::text").get()
    )
    if not name and not title:
        return {}

    return {
        "name": name.strip() if name else None,
        "title": title.strip() if title else None,
        "url": profile_url,
        "source": "linkedin",
        "company": _company_from_title(title) if title else None,
    }


def _company_from_title(title: str) -> str | None:
    if " at " in title:
        return title.split(" at ", 1)[-1].strip()
    if " @ " in title:
        return title.split(" @ ", 1)[-1].strip()
    return None


def linkedin_search_urls_for_company(company: str) -> list[str]:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", company.lower()).strip("-")
    if not slug:
        return []
    return [f"https://www.linkedin.com/company/{slug}/people/"]
