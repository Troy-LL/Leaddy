from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
from scrapers import fetch_linkedin, scrape_company_urls, search_google
from scrapers.linkedin import linkedin_search_urls_for_company

load_dotenv()

logger = logging.getLogger("leadgen")
logging.basicConfig(level=logging.INFO)

lead_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
_background_tasks: set[asyncio.Task[Any]] = set()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def supervisor(coro_factory, *, max_crashes: int = 5, window_secs: float = 60.0):
    crash_times: deque[float] = deque(maxlen=max_crashes)
    while True:
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Supervised task crashed")
            crash_times.append(monotonic())
            if len(crash_times) == max_crashes and crash_times[0] > monotonic() - window_secs:
                raise
            await asyncio.sleep(1)


async def broadcaster() -> None:
    while True:
        item = await lead_queue.get()
        try:
            saved = await db.insert_lead(item)
            await manager.broadcast(json.dumps(saved))
        except Exception:
            logger.exception("Broadcaster failed for lead")
        finally:
            lead_queue.task_done()


def _enrich_lead(raw: dict[str, Any], query: str) -> dict[str, Any]:
    return {
        "id": raw.get("id") or str(uuid4()),
        "name": raw.get("name"),
        "email": raw.get("email"),
        "company": raw.get("company"),
        "title": raw.get("title"),
        "source": raw.get("source", "unknown"),
        "url": raw.get("url"),
        "score": raw.get("score", 0.5),
        "query": query,
    }


async def run_scrape(job_id: str, query: str, sources: list[str]) -> None:
    await db.update_job_status(job_id, "running")
    try:
        company_urls: list[str] = []

        if "google" in sources:
            for hit in await search_google(query):
                lead = _enrich_lead(
                    {
                        "company": hit.get("company"),
                        "url": hit.get("url"),
                        "source": "google",
                        "score": 0.4,
                    },
                    query,
                )
                await lead_queue.put(lead)
                if hit.get("url"):
                    company_urls.append(hit["url"])

        if "company" in sources and company_urls:
            for lead_raw in await scrape_company_urls(company_urls):
                await lead_queue.put(_enrich_lead({**lead_raw, "score": 0.6}, query))

        if "linkedin" in sources and os.getenv("LI_AT"):
            targets = company_urls[:5]
            for url in targets:
                if "linkedin.com/in/" in url:
                    profile = await fetch_linkedin(url)
                    if profile:
                        await lead_queue.put(_enrich_lead({**profile, "score": 0.8}, query))
            for url in targets:
                company_name = url
                if "://" in url:
                    from urllib.parse import urlparse

                    company_name = urlparse(url).netloc
                for li_url in linkedin_search_urls_for_company(company_name)[:1]:
                    profile = await fetch_linkedin(li_url)
                    if profile:
                        await lead_queue.put(_enrich_lead({**profile, "score": 0.75}, query))

        await db.update_job_status(job_id, "done")
    except Exception:
        logger.exception("Scrape job %s failed", job_id)
        await db.update_job_status(job_id, "failed")


class ScrapeRequest(BaseModel):
    query: str
    sources: list[str] = Field(default_factory=lambda: ["google", "company", "linkedin"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    task = asyncio.create_task(supervisor(broadcaster))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    yield


app = FastAPI(title="LeadGen Harness API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    existing = await db.find_running_job_for_query(req.query)
    if existing:
        return {"job_id": existing["id"], "status": "already_running"}

    job_id = str(uuid4())
    await db.create_job(job_id, req.query)
    sources = req.sources or ["google", "company", "linkedin"]
    task = asyncio.create_task(run_scrape(job_id, req.query, sources))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/leads")
async def list_leads(
    company: str | None = None,
    source: str | None = None,
    min_score: float | None = None,
    limit: int = 100,
):
    return await db.get_leads(
        company=company,
        source=source,
        min_score=min_score,
        limit=limit,
    )


@app.websocket("/stream")
async def stream(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
