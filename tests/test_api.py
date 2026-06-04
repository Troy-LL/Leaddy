"""API smoke tests — run with backend on localhost:8000."""

from __future__ import annotations

import os

import httpx
import pytest

BASE = os.getenv("TEST_API_URL", "http://localhost:8000")


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        yield c


def test_health(client: httpx.Client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_scrape_and_job(client: httpx.Client):
    r = client.post(
        "/scrape",
        json={"query": "test fintech CTO", "sources": ["google"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    job = client.get(f"/jobs/{data['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] in ("queued", "running", "done", "failed")


def test_list_leads(client: httpx.Client):
    r = client.get("/leads", params={"limit": 10})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
