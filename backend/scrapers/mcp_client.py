"""HTTP client for Scrapling MCP server (streamable HTTP mode)."""

from __future__ import annotations

import os
from typing import Any

import httpx

SCRAPLING_MCP_URL = os.getenv("SCRAPLING_MCP_URL", "http://localhost:8001").rstrip("/")
TIMEOUT = float(os.getenv("SCRAPLING_MCP_TIMEOUT", "120"))


async def _call_tool(tool: str, arguments: dict[str, Any]) -> Any:
    """Invoke an MCP tool over HTTP. Falls back to empty on failure."""
    payload = {"tool": tool, "arguments": arguments}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{SCRAPLING_MCP_URL}/tools/{tool}", json=arguments)
            if resp.status_code == 404:
                resp = await client.post(f"{SCRAPLING_MCP_URL}/{tool}", json=arguments)
            if resp.status_code == 404:
                resp = await client.post(f"{SCRAPLING_MCP_URL}/mcp", json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


async def bulk_fetch(
    urls: list[str],
    *,
    css_selector: str | None = None,
) -> list[dict[str, Any]]:
    data = await _call_tool(
        "bulk_fetch",
        {
            "urls": urls,
            "css_selector": css_selector,
            "main_content_only": True,
        },
    )
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("items", [data]))
    return []


async def stealthy_fetch(
    url: str,
    *,
    cookies: dict[str, str] | None = None,
    css_selector: str | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    args: dict[str, Any] = {"url": url, "headless": headless, "main_content_only": True}
    if cookies:
        args["cookies"] = cookies
    if css_selector:
        args["css_selector"] = css_selector
    data = await _call_tool("stealthy_fetch", args)
    if isinstance(data, dict):
        return data
    return {}


async def get_page(url: str, *, css_selector: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"url": url, "main_content_only": True}
    if css_selector:
        args["css_selector"] = css_selector
    data = await _call_tool("get", args)
    if isinstance(data, dict):
        return data
    return {"content": data if isinstance(data, str) else ""}
