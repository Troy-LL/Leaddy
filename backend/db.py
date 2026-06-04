"""SQLite persistence for leads and scrape jobs."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_URL", "sqlite:///./leads.db").replace(
    "sqlite:///", ""
).replace("sqlite:////", "/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                company TEXT,
                title TEXT,
                source TEXT,
                url TEXT,
                score REAL,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        await db.commit()


async def insert_lead(lead: dict[str, Any]) -> dict[str, Any]:
    lead_id = lead.get("id") or str(uuid4())
    created_at = lead.get("created_at") or _now()
    row = {
        "id": lead_id,
        "name": lead.get("name"),
        "email": lead.get("email"),
        "company": lead.get("company"),
        "title": lead.get("title"),
        "source": lead.get("source"),
        "url": lead.get("url"),
        "score": lead.get("score"),
        "created_at": created_at,
    }
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO leads (id, name, email, company, title, source, url, score, created_at)
            VALUES (:id, :name, :email, :company, :title, :source, :url, :score, :created_at)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                email=excluded.email,
                company=excluded.company,
                title=excluded.title,
                source=excluded.source,
                url=excluded.url,
                score=excluded.score
            """,
            row,
        )
        await db.commit()
    return row


async def get_leads(
    *,
    company: str | None = None,
    source: str | None = None,
    min_score: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM leads WHERE 1=1"
    params: list[Any] = []
    if company:
        query += " AND company LIKE ?"
        params.append(f"%{company}%")
    if source:
        query += " AND source = ?"
        params.append(source)
    if min_score is not None:
        query += " AND score >= ?"
        params.append(min_score)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def create_job(job_id: str, query: str) -> dict[str, Any]:
    row = {
        "id": job_id,
        "query": query,
        "status": "queued",
        "created_at": _now(),
        "finished_at": None,
    }
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO jobs (id, query, status, created_at, finished_at)
            VALUES (:id, :query, :status, :created_at, :finished_at)
            """,
            row,
        )
        await db.commit()
    return row


async def update_job_status(job_id: str, status: str) -> None:
    finished_at = _now() if status in ("done", "failed") else None
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE jobs SET status = ?, finished_at = COALESCE(?, finished_at)
            WHERE id = ?
            """,
            (status, finished_at, job_id),
        )
        await db.commit()


async def get_job(job_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def find_running_job_for_query(query: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE query = ? AND status = 'running' LIMIT 1",
            (query,),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None
