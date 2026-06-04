# LeadGen Harness — Build Plan

> Full project blueprint. Read this file to understand every architectural decision, known risk, its fix, and the build sequence before touching any code.

---

## What This Project Is

A self-contained lead generation harness. A user types a natural-language target (e.g. "find CTOs at Series A fintech startups in Southeast Asia") into a React dashboard, a built-in LLM agent, or an external agent runtime. The scraping pipeline uses Scrapling to crawl Google SERP → company websites → LinkedIn profiles. Leads flow into a SQLite database and stream live to the dashboard via WebSocket as they are found.

**The agent is optional.** The system works at three levels so anyone can use it regardless of what tools they have installed.

---

## Usage Tiers — Pick Your Entry Point

**Level 1 — No agent, just the dashboard** _(easiest, zero extra setup)_
- `docker-compose up` — starts backend, frontend, and the Scrapling MCP service
- Use the search bar in the React dashboard to trigger scrapes directly
- Results stream in live. Filter, export CSV. Done.
- Requirements: Docker only. No API keys needed.

**Level 2 — Simple built-in agent** _(recommended default for most users)_
- `docker-compose --profile simple-agent up`
- `agent/simple_agent.py` — a self-contained LLM tool-calling loop using the OpenAI SDK
- Compatible with OpenAI, Anthropic (via their compat endpoint), or any local model via Ollama (`LLM_BASE_URL=http://host.docker.internal:11434/v1`) — free if running locally
- The agent decomposes complex queries, coordinates multi-stage scraping, and scores/ranks results
- Requirements: Docker + one API key (or a local model, which is free)

**Level 3 — External agent runtime** _(for users who already have OpenClaw or Hermes)_
- `docker-compose --profile openclaw up` or `docker-compose --profile hermes up`
- Uses the `agent/skill.md` manifest with the full external runtime
- Requirements: Docker + OpenClaw or Hermes installed + API key

> All three levels share the same backend, database, and dashboard. The agent layer is additive — it just makes query decomposition and result scoring smarter.

---

## Architecture Overview

```
User input
    │
    ├─ Level 1: React dashboard search bar
    │           → POST /scrape directly (no agent at all)
    │
    ├─ Level 2: agent/simple_agent.py  (built-in, Docker profile: simple-agent)
    │           OpenAI SDK · any OpenAI-compat URL · Ollama for local/free use
    │           LLM_BASE_URL=http://host.docker.internal:11434/v1  ← Ollama example
    │
    └─ Level 3: OpenClaw / Hermes  (Docker profile: openclaw | hermes)
                agent/skill.md manifest
    │
    ▼  (all three paths converge at the same FastAPI endpoints)
FastAPI backend — port 8000  (lightweight python:3.11-slim, no browsers)
  POST /scrape · GET /leads · GET /jobs/{id} · WebSocket /stream
        │
        ├──→ google.py  ──→ AsyncFetcher (HTTP, no browser)
        ├──→ company.py ──→ POST http://scrapling_mcp:8001/bulk_fetch
        └──→ linkedin.py──→ POST http://scrapling_mcp:8001/stealthy_fetch
                                    │
                        ┌───────────┴────────────┐
                        │  scrapling_mcp  :8001   │
                        │  pyd4vinci/scrapling    │
                        │  official image —       │
                        │  all browsers pre-baked │
                        └────────────────────────┘
        │
        ▼
asyncio.Queue → insert_lead() + manager.broadcast()
        │
        ▼
SQLite  leads.db  (Docker named volume — persists across restarts)
  leads table · jobs table · WAL mode
        │
        ▼
React dashboard — port 5173
  Live WebSocket feed · filterable table · CSV export · job status indicator
```

---

## Repo Layout

```
leadgen-harness/
├── PLAN.md                        ← this file
├── .env.example                   ← all required env vars with comments
├── docker-compose.yml             ← 4 base services + 3 optional agent profiles
├── .agents/
│   └── skills/                    ← project-local agent skills (not global)
│       ├── vercel-react-best-practices/
│       ├── webapp-testing/
│       ├── devops-engineer/
│       ├── web-scraping/
│       └── sqlite-database-expert/
├── agent/
│   ├── simple_agent.py            ← Level 2: built-in LLM agent (OpenAI SDK, Ollama-compatible)
│   ├── simple.Dockerfile          ← python:3.11-slim + openai + httpx (~50 MB)
│   ├── openclaw.Dockerfile        ← Level 3: OpenClaw runtime container
│   ├── hermes.Dockerfile          ← Level 3: Hermes runtime container
│   └── skill.md                   ← AgentSkill manifest for Level 3 runtimes
├── backend/
│   ├── Dockerfile                 ← python:3.11-slim, NO browser deps (lightweight)
│   ├── requirements.txt           ← scrapling, fastapi, aiosqlite, httpx, uvicorn
│   ├── main.py                    ← FastAPI app
│   ├── db.py                      ← aiosqlite: leads + jobs tables, WAL mode
│   └── scrapers/
│       ├── __init__.py
│       ├── google.py              ← AsyncFetcher (HTTP direct, no MCP needed)
│       ├── company.py             ← calls scrapling_mcp:8001/bulk_fetch via httpx
│       └── linkedin.py            ← calls scrapling_mcp:8001/stealthy_fetch via httpx
└── frontend/
    ├── package.json
    ├── vite.config.js             ← dev proxy to :8000
    └── src/
        ├── App.jsx                ← layout shell + search bar + agent mode selector
        ├── LeadFeed.jsx           ← live WebSocket feed + auto-reconnect
        └── LeadTable.jsx          ← filterable table + dedupe + CSV export
```

> `scrapling_mcp` is not a code folder — it uses the official `pyd4vinci/scrapling` image directly, configured in `docker-compose.yml`.

---

## Phase 1 — Backend Core

### `backend/requirements.txt`

```
fastapi
uvicorn[standard]
aiosqlite
pydantic
python-dotenv
httpx
scrapling
```

`scrapling` (no extras) — only the parser and `AsyncFetcher` (HTTP) are needed in the backend container. All browser automation (`StealthyFetcher`, `DynamicFetcher`, Playwright) runs in the dedicated `scrapling_mcp` container. Python 3.10 minimum required.

> The old plan had `scrapling[fetchers]` here, which would have added ~1 GB of browser binaries to the backend image. The Scrapling README confirmed there is an official Docker image (`pyd4vinci/scrapling`) that already has everything — using it as the MCP service is the right call.

---

### `backend/db.py`

Active skill: `sqlite-database-expert`

Two tables. `PRAGMA journal_mode=WAL` is set in `init_db()` to prevent write contention when concurrent scrapers write simultaneously.

**Schema:**

```
leads
  id          TEXT  PRIMARY KEY   (UUID)
  name        TEXT
  email       TEXT
  company     TEXT
  title       TEXT
  source      TEXT                (google | company | linkedin)
  url         TEXT
  score       REAL                (0.0–1.0, agent-assigned relevance)
  created_at  TEXT                (ISO 8601)

jobs
  id          TEXT  PRIMARY KEY   (UUID)
  query       TEXT
  status      TEXT                (queued | running | done | failed)
  created_at  TEXT
  finished_at TEXT                (NULL until terminal state)
```

**Exported functions:**

- `init_db()` — creates tables + sets WAL mode
- `insert_lead(lead: dict)` — upsert by id
- `get_leads(company, source, min_score, limit)` → list of dicts
- `create_job(job_id, query)` → None
- `update_job_status(job_id, status)` → None
- `get_job(job_id)` → dict or None

---

### `backend/main.py`

Active skill: (no specific skill — core FastAPI patterns)

#### Windows event loop fix

Must be the very first two lines of the file, before any other imports:

```python
import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
```

Without this, Playwright subprocesses raise `NotImplementedError` on Windows due to `SelectorEventLoop` incompatibility.

#### CORS middleware

FastAPI on :8000 and Vite on :5173 are different origins. Without this every browser request fails:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### ProcessPoolExecutor (lifespan)

Initialized once at startup, stored on `app.state`. Never created per-request (creating a pool per request is expensive and causes resource exhaustion):

```python
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.executor = ProcessPoolExecutor(max_workers=2)
    broadcaster_task = asyncio.create_task(supervisor(broadcaster))
    _background_tasks.add(broadcaster_task)
    broadcaster_task.add_done_callback(_background_tasks.discard)
    await init_db()
    yield
    app.state.executor.shutdown(wait=True)
```

#### Supervisor (broadcaster crash recovery)

The broadcaster drains `asyncio.Queue` → writes to DB → broadcasts to all WebSocket clients. If it crashes, this wrapper restarts it with backoff. Stops restarting after 5 crashes in 60 seconds (signals a real bug rather than transient error):

```python
async def supervisor(coro_factory, *, max_crashes=5, window_secs=60):
    from collections import deque
    from time import monotonic
    crash_times = deque(maxlen=max_crashes)
    while True:
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            crash_times.append(monotonic())
            if (len(crash_times) == max_crashes and
                    crash_times[0] > monotonic() - window_secs):
                raise  # crash loop — die loudly
            await asyncio.sleep(1)
```

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/scrape` | Accepts `{query, sources}`. Generates UUID job_id. Writes `jobs` row (`status=queued`). Fires `asyncio.create_task(run_scrape(...))`. Returns `{job_id}`. Deduplication: skips if a job with the same query is already `running`. |
| `GET` | `/jobs/{job_id}` | Returns job row from DB. Frontend polls this to show progress indicator. |
| `GET` | `/leads` | Query params: `company`, `source`, `min_score`, `limit`. Returns filtered JSON array. |
| `WS` | `/stream` | WebSocket. `ConnectionManager` holds active connections. Broadcaster pushes each new lead as JSON. |

#### Background scrape task flow

```
run_scrape(job_id, query, sources)
  update_job_status(job_id, "running")
  ├── google.py  → yields company URLs         → put on asyncio.Queue
  ├── company.py → yields leads from each URL  → put on asyncio.Queue
  └── linkedin.py → enriches leads             → put on asyncio.Queue
  update_job_status(job_id, "done" | "failed")

broadcaster() — runs forever under supervisor
  item = await queue.get()
  await insert_lead(item)
  await manager.broadcast(json.dumps(item))
```

---

## Phase 2 — Scrapers

Active skill: `web-scraping`

> Security note: `web-scraping` skill is rated `Gen: Low Risk / Snyk: Med Risk`. Review all generated scraper code before running.

### `backend/scrapers/google.py`

Uses `AsyncFetcher` — pure HTTP with stealthy headers, no browser spin-up needed for SERP pages. If `GOOGLE_SERP_KEY` is set in env, uses a paid API instead (more reliable at scale):

```python
from scrapling.fetchers import AsyncFetcher

async def search_google(query: str) -> list[dict]:
    url = f"https://www.google.com/search?q={quote(query)}&num=20"
    page = await AsyncFetcher.fetch(url, stealthy_headers=True)
    results = []
    for block in page.css(".g"):
        title = block.css("h3::text").get()
        link  = block.css("a::attr(href)").get()
        if title and link:
            results.append({"company": title, "url": link})
    return results
```

### `backend/scrapers/company.py`

Calls the `scrapling_mcp` service's `bulk_fetch` tool for JS-heavy pages, `bulk_get` for static pages. The MCP service handles session management, concurrency, and anti-bot bypass. Results are parsed with Scrapling's parser (available without `[fetchers]`):

```python
import httpx
from scrapling.parser import Selector

async def scrape_company_urls(urls: list[str]) -> list[dict]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "http://scrapling_mcp:8001/bulk_fetch",
            json={"urls": urls, "css_selector": "a[href^='mailto'], .team-member, h3"}
        )
    results = []
    for page_data in resp.json():
        page = Selector(page_data.get("content", ""))
        # parse names, emails, titles from returned content
        ...
    return results
```

**Dev mode** (for development without hitting live sites): Spider's `dev_mode=True` caches responses to disk on first run and replays them. Use this when iterating on parse logic.

**Pause/resume** for long crawls: pass `crawldir="./crawl_data"` to the Spider constructor — press Ctrl+C to pause gracefully, restart with same `crawldir` to resume.

### `backend/scrapers/linkedin.py`

Calls the `scrapling_mcp` service's `stealthy_fetch` tool via HTTP. No Playwright, no ProcessPoolExecutor, no Windows event loop issues in this process:

```python
import httpx, os

async def fetch_linkedin(profile_url: str) -> dict:
    li_at = os.getenv("LI_AT", "")
    if not li_at:
        return {}  # graceful degradation — skip LinkedIn layer
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "http://scrapling_mcp:8001/stealthy_fetch",
            json={
                "url": profile_url,
                "cookies": {"li_at": li_at},
                "css_selector": ".top-card-layout__title, .top-card-layout__headline",
                "headless": True
            }
        )
    data = resp.json()
    return {"name": data.get("title"), "source": "linkedin", "url": profile_url}
```

**LinkedIn risks (unchanged):**
- `LI_AT` cookie expires ~1 year and can be revoked at any time. No auto-refresh mechanism.
- Scraping LinkedIn violates their ToS. Use only for personal/research purposes.
- If cookie is unset, LinkedIn layer is skipped entirely — Google + company layers still run.

---

## Phase 3 — React Frontend

Active skill: `vercel-react-best-practices`

### `frontend/vite.config.js`

Dev proxy so the browser never does cross-origin requests during local development:

```js
export default {
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/stream": { target: "ws://localhost:8000", ws: true },
    }
  }
}
```

### `frontend/src/LeadFeed.jsx`

- Opens WebSocket on mount to `ws://localhost:8000/stream`
- `onmessage` → parses JSON → appends to local state list (capped at last 50 for performance)
- Shows a pulsing green "LIVE" indicator while connected
- **Auto-reconnect**: exponential backoff (1s → 2s → 4s → 8s → 16s), max 5 attempts, shows "Reconnecting…" status between attempts

### `frontend/src/LeadTable.jsx`

- On mount: fetches `GET /leads` for historical data
- Merges with live WebSocket feed using `id` field as deduplication key — prevents double-rows when a lead arrives over the socket before the initial HTTP response resolves
- Client-side filter inputs: company name, source (google | company | linkedin), minimum score slider
- "Export CSV" button: serializes the current filtered view to a CSV blob and triggers browser download — no server round-trip needed

### `frontend/src/App.jsx`

- Top bar: search input + "Scrape" button → `POST /scrape` → stores `job_id` in state
- Job status badge: polls `GET /jobs/{job_id}` every 2 seconds while `status !== "done" && status !== "failed"`
- Left sidebar: `<LeadFeed>` (live stream)
- Main panel: `<LeadTable>` (full table)

---

## Phase 4a — Simple Built-in Agent (Level 2)

### `agent/simple_agent.py`

A self-contained tool-calling loop. No external runtime. The `LLM_BASE_URL` env var makes it work with any provider:

```python
from openai import OpenAI
import httpx, os, json, sys, time

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY", "ollama"),     # "ollama" for local models
    base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
)
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

TOOLS = [
    {"type": "function", "function": {
        "name": "scrape_leads",
        "description": "Start a lead scrape job. Returns job_id immediately.",
        "parameters": {"type": "object", "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"},
                            "default": ["google", "company", "linkedin"]}
            }}
    }},
    {"type": "function", "function": {
        "name": "get_job",
        "description": "Poll job status. Call until status is 'done' or 'failed'.",
        "parameters": {"type": "object", "required": ["job_id"],
            "properties": {"job_id": {"type": "string"}}}
    }},
    {"type": "function", "function": {
        "name": "get_leads",
        "description": "Retrieve collected leads with optional filters.",
        "parameters": {"type": "object",
            "properties": {
                "min_score": {"type": "number"},
                "limit": {"type": "integer", "default": 50}
            }}
    }}
]

def call_tool(name, args):
    with httpx.Client(base_url=BACKEND, timeout=30) as http:
        if name == "scrape_leads":
            return http.post("/scrape", json=args).json()
        if name == "get_job":
            return http.get(f"/jobs/{args['job_id']}").json()
        if name == "get_leads":
            return http.get("/leads", params=args).json()

def run(user_query: str):
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_query}]
    while True:
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=messages, tools=TOOLS, tool_choice="auto"
        )
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            print(msg.content)
            break
        for tc in msg.tool_calls:
            result = call_tool(tc.function.name, json.loads(tc.function.arguments))
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)})

if __name__ == "__main__":
    run(" ".join(sys.argv[1:]) or input("Target description: "))
```

**Supported LLM providers** — all via `LLM_BASE_URL`:

| Provider | `LLM_BASE_URL` | Cost |
|----------|---------------|------|
| OpenAI | `https://api.openai.com/v1` (default) | Paid |
| Anthropic | `https://api.anthropic.com/v1` | Paid |
| Ollama (local) | `http://host.docker.internal:11434/v1` | Free |
| Any OpenAI-compat API | Custom URL | Varies |

### `agent/simple.Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir openai httpx
COPY simple_agent.py .
ENTRYPOINT ["python", "simple_agent.py"]
```

~50 MB image. No browser deps, no external runtime.

---

## Phase 4b — External Agent Skill Manifest (Level 3)

### `agent/skill.md`

Everything in one file. YAML frontmatter holds the prompts; the body documents the tools. No `prompts.py` — agent runtimes (OpenClaw and Hermes) load all fields directly from the manifest.

```yaml
---
system_prompt: |
  You are a lead generation agent. Given a target description, break it down
  into scrape tasks. Use the pipeline: Google SERP discovery → company site
  enrichment → LinkedIn profile depth. Call scrape_leads to start a job, poll
  get_job until status is "done", then call get_leads to retrieve and score
  the results. Assign a relevance score (0–1) to each lead based on how well
  it matches the original target description.

extraction_prompt: |
  From the raw scraped content, extract these fields where present:
  name, title, company, email, linkedin_url, company_website.
  Return as JSON. If a field is not found, omit it (do not return null).
  Assign relevance_score (0.0–1.0) based on match to the search query.

tools:
  - name: scrape_leads
    description: Start a lead generation scrape job. Returns a job_id immediately.
    endpoint: POST http://backend:8000/scrape
    parameters:
      query: string        # natural language target description
      sources: array       # subset of [google, company, linkedin]
    returns:
      job_id: string

  - name: get_job
    description: Poll the status of a running scrape job.
    endpoint: GET http://backend:8000/jobs/{job_id}
    returns:
      status: string       # queued | running | done | failed

  - name: get_leads
    description: Retrieve collected leads with optional filters.
    endpoint: GET http://backend:8000/leads
    parameters:
      company: string?
      source: string?
      min_score: number?
      limit: integer?
---
```

---

## Phase 5 — Docker Compose

Active skill: `devops-engineer`

### Base services (always running)

| Service | Base | Port | Notes |
|---------|------|------|-------|
| `backend` | `python:3.11-slim` | 8000 | Lightweight — no browser deps |
| `frontend` | `node:20-alpine` | 5173 | `CHOKIDAR_USEPOLLING=true` for Windows HMR |
| `scrapling_mcp` | `pyd4vinci/scrapling:latest` | 8001 | Official image, all browsers pre-baked. Pulled, not built. |

### Agent services (Docker Compose profiles — opt-in)

Agent services use profiles so `docker-compose up` alone starts only the core 3 services. Users pick exactly what they need:

```yaml
# Level 2 — built-in agent (profile: simple-agent)
agent_simple:
  build: { context: ./agent, dockerfile: simple.Dockerfile }
  profiles: [simple-agent]
  environment:
    LLM_API_KEY: ${LLM_API_KEY}
    LLM_BASE_URL: ${LLM_BASE_URL:-https://api.openai.com/v1}
    LLM_MODEL: ${LLM_MODEL:-gpt-4o-mini}
    BACKEND_URL: http://backend:8000
  depends_on: [backend]

# Level 3a — OpenClaw (profile: openclaw)
agent_openclaw:
  build: { context: ./agent, dockerfile: openclaw.Dockerfile }
  profiles: [openclaw]
  depends_on: [backend]

# Level 3b — Hermes (profile: hermes)
agent_hermes:
  build: { context: ./agent, dockerfile: hermes.Dockerfile }
  profiles: [hermes]
  depends_on: [backend]
```

**Startup commands by tier:**

```bash
# Level 1 — no agent, just the dashboard
docker-compose up

# Level 2 — simple built-in agent
docker-compose --profile simple-agent up

# Level 3 — OpenClaw
docker-compose --profile openclaw up

# Level 3 — Hermes
docker-compose --profile hermes up
```

### Named volume

SQLite database persists across restarts via named volume:

```yaml
volumes:
  leads_data:
services:
  backend:
    volumes:
      - leads_data:/app/data
```

`DATABASE_URL=sqlite:////app/data/leads.db` (four slashes = absolute path inside container)

### `.env.example`

```env
# ── Agent tier ──────────────────────────────────────────────────────────────
# Start with no agent: docker-compose up
# Simple agent:        docker-compose --profile simple-agent up
# OpenClaw:            docker-compose --profile openclaw up
# Hermes:              docker-compose --profile hermes up

# Level 2 simple agent settings
LLM_API_KEY=sk-...                            # OpenAI key, or "ollama" for local
LLM_BASE_URL=https://api.openai.com/v1        # or http://host.docker.internal:11434/v1
LLM_MODEL=gpt-4o-mini                         # or llama3, mistral, etc.

# ── Scrapers ────────────────────────────────────────────────────────────────
# LinkedIn session cookie (optional — layer skipped if unset)
LI_AT=

# Google SERP API key (optional — falls back to direct fetch if unset)
GOOGLE_SERP_KEY=

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL=sqlite:////app/data/leads.db

# ── Internal service URLs ───────────────────────────────────────────────────
SCRAPLING_MCP_URL=http://scrapling_mcp:8001
```

---

## Scrapling API Reference (from official README)

Key classes and when to use each — from the official `D4Vinci/Scrapling` repo (60.9K stars, v0.4.8, actively maintained):

| Class | Use case | Browser? | In our project |
|-------|----------|----------|----------------|
| `AsyncFetcher` | Fast HTTP, no JS needed | No | `google.py` — SERP parsing |
| `Fetcher` / `FetcherSession` | HTTP with TLS fingerprint impersonation | No | Alternative for static company pages |
| `DynamicFetcher` / `DynamicSession` | Full browser automation, no anti-bot | Yes | Available via MCP `fetch` tool |
| `StealthyFetcher` / `StealthySession` | Anti-bot bypass, Cloudflare Turnstile | Yes | `linkedin.py` via MCP `stealthy_fetch` |
| `AsyncStealthySession` | Async-native stealthy browser | Yes | Available via MCP `bulk_stealthy_fetch` |
| `Spider` | Full concurrent crawl with pause/resume | Configurable | `company.py` — multi-page crawls |

**Install commands (correct, from README):**
```bash
pip install scrapling                # parser + HTTP fetcher only
pip install "scrapling[fetchers]"    # + browser automation
scrapling install                    # install browser binaries (after [fetchers])
pip install "scrapling[ai]"          # + MCP server feature
pip install "scrapling[all]"         # everything
```

> Note: Our `backend/` only needs `pip install scrapling` (no extras). The `scrapling_mcp` container uses the official image which has `[all]` pre-installed.

**Official agent skill for OpenClaw** (installable via Clawhub):
```bash
clawhub install scrapling-official
```
This skill teaches the agent how to write and use Scrapling code. It complements our `agent/skill.md` (which defines the lead-gen workflow tools) — they serve different purposes.

**Spider features available (use during development):**
- `dev_mode=True` — caches pages to disk on first run, replays on subsequent runs (no re-hitting target servers while iterating)
- `crawldir="./crawl_data"` — pause/resume long crawls (Ctrl+C saves state, restart resumes)
- `configure_sessions(manager)` — route requests to different session types within one spider

---

## Known Risks and Their Fixes

Every risk listed here was identified before writing any code. The fix is already baked into the build plan above.

| Risk | Impact | Fix |
|------|--------|-----|
| Playwright incompatible with `SelectorEventLoop` on Windows | Runtime crash on first scrape | `WindowsProactorEventLoopPolicy()` at top of `main.py` before all imports. Note: only affects `backend` process — Scrapling MCP container runs on Linux/Docker and is unaffected. |
| ~~ProcessPoolExecutor on Windows~~ | ~~Pickle errors in subprocess~~ | **Eliminated** — browser automation moved to `scrapling_mcp` container. `backend` scrapers call MCP via HTTP (`httpx`). No ProcessPoolExecutor needed. |
| CORS not configured | Every browser request to :8000 fails silently | `CORSMiddleware` with explicit `allow_origins=["http://localhost:5173"]` |
| SQLite data lost on container restart | All leads wiped on every `docker-compose down` | Named Docker volume `leads_data:/app/data` |
| SQLite write contention under concurrent scrapers | Intermittent `database is locked` errors | `PRAGMA journal_mode=WAL` in `init_db()` |
| Broadcaster `asyncio.Task` crashes silently | Live feed goes dead with no visible error | `supervisor()` wrapper with crash-loop detector (5 crashes / 60s = raise) |
| No job tracking on `POST /scrape` | No progress feedback, double-scrape if clicked twice | `jobs` table + `GET /jobs/{job_id}` + dedup check before queuing |
| Deduplication gap between WS feed and initial HTTP fetch | Leads appear twice in table | Dedup by `id` field in `LeadTable` before render |
| WebSocket drops silently | Live feed goes dead, user unaware | Exponential backoff reconnect in `LeadFeed` (max 5 retries) |
| LinkedIn ToS violation + cookie expiry | Account ban, auth failure | Cookie optional + graceful skip, documented in `.env.example` |
| Google SERP blocks at scale | IP blocks after ~100 requests | `GOOGLE_SERP_KEY` opt-in for paid API; rate limiting via MCP `concurrent_requests` |
| ~~Docker image size (~1 GB)~~ | ~~Slow first build~~ | **Eliminated** — `pyd4vinci/scrapling` is pulled (not built). Backend image is lightweight `python:3.11-slim`. |
| `scrapling_mcp` service unavailable on startup | Backend scrapers get connection errors | Add `depends_on: scrapling_mcp` + health check in `docker-compose.yml` |

---

## Active Skills (project-local, not global)

All skills are installed under `.agents/skills/` in this project folder. They are not installed globally.

| Skill | Version source | Installs | Apply when building |
|-------|---------------|----------|---------------------|
| `vercel-react-best-practices` | vercel-labs/agent-skills | 450K | `frontend/src/*.jsx` |
| `webapp-testing` | anthropics/skills | 88.1K | E2E tests (Playwright) |
| `devops-engineer` | jeffallan/claude-skills | 5.7K | `docker-compose.yml` + Dockerfiles |
| `web-scraping` | mindrally/skills | 3.1K | `backend/scrapers/` |
| `sqlite-database-expert` | martinholovsky/claude-skills-generator | 1.8K | `backend/db.py` |

Skills excluded and why:
- `nexu-io/open-design@frontend-design` — 896 installs, below 1K threshold
- `affaan-m/everything-claude-code@django-tdd` — 5.2K installs but Django-specific, wrong framework
- All other candidates — below 100 installs

---

## Build Order

Follow this sequence. Each step depends on the previous one.

1. **`backend/db.py`** — schema, WAL mode, all CRUD functions
   - Activate skill: `sqlite-database-expert`

2. **`backend/main.py`** — Windows event loop fix, CORS, lifespan, supervisor-wrapped broadcaster, all four endpoints

3. **`backend/scrapers/`** — google (AsyncFetcher) → company (MCP bulk_fetch) → linkedin (MCP stealthy_fetch)
   - Activate skill: `web-scraping`
   - Review generated code before running (Snyk Med Risk rating)

4. **Wire pipeline** — `run_scrape()` background task: job status transitions + queue feed

5. **`frontend/`** — Vite scaffold → `LeadTable.jsx` → `LeadFeed.jsx` → `App.jsx`
   - Activate skill: `vercel-react-best-practices`

6. **`agent/simple_agent.py` + `agent/simple.Dockerfile`** — Level 2 built-in agent

7. **`agent/skill.md`** — Level 3 manifest, YAML frontmatter, three tool definitions

8. **Docker** — `backend/Dockerfile`, `agent/simple.Dockerfile`, `agent/openclaw.Dockerfile`, `agent/hermes.Dockerfile`, `docker-compose.yml` (3 base services + 3 agent profiles + health checks + named volume), `.env.example`
   - Activate skill: `devops-engineer`

9. **E2E tests** — Playwright scripts testing all three tiers
   - Activate skill: `webapp-testing`

---

## Architecture Overview (updated)

```
User input (search prompt or target list)
        │
        ▼
Agent runtime — OpenClaw or Hermes
        │  calls POST /scrape
        ▼
FastAPI backend — port 8000 (lightweight container, no browsers)
  POST /scrape · GET /leads · GET /jobs/{id} · WebSocket /stream
        │
        ├──→ google.py  ──→ AsyncFetcher (HTTP directly, no MCP needed)
        │
        ├──→ company.py ──→ POST http://scrapling_mcp:8001/bulk_fetch
        │                           │
        └──→ linkedin.py──→ POST http://scrapling_mcp:8001/stealthy_fetch
                                    │
                        ┌───────────┴───────────┐
                        │  scrapling_mcp :8001   │
                        │  pyd4vinci/scrapling   │
                        │  (all browsers baked   │
                        │   in official image)   │
                        └───────────────────────┘
        │ (results flow back as JSON)
        ▼
asyncio.Queue → insert_lead() + manager.broadcast()
        │
        ▼
SQLite / leads.db  (Docker named volume)
        │
        ▼
React dashboard — port 5173
  Live WebSocket feed · filterable table · CSV export · job status indicator
```

---

## How to Run (after build)

```bash
# 1. Copy env file
cp .env.example .env
# Edit .env — at minimum, no changes needed for Level 1

# ── Level 1: No agent, just dashboard ───────────────────────────────────────
docker-compose up --build
# Open: http://localhost:5173
# Type a query in the search bar and hit Scrape

# ── Level 2: Simple built-in agent ──────────────────────────────────────────
# Set LLM_API_KEY in .env (or point LLM_BASE_URL at Ollama for free local use)
docker-compose --profile simple-agent up --build
# The agent runs automatically and processes queries from the dashboard

# ── Level 3: OpenClaw ───────────────────────────────────────────────────────
docker-compose --profile openclaw up --build

# ── Level 3: Hermes ─────────────────────────────────────────────────────────
docker-compose --profile hermes up --build

# Backend Swagger UI (all tiers)
# http://localhost:8000/docs
```

For local development without Docker:

```bash
# Scrapling MCP (required for company + linkedin scrapers)
docker run -p 8001:8001 pyd4vinci/scrapling scrapling mcp --http --host 0.0.0.0 --port 8001

# Backend
cd backend
pip install -r requirements.txt
# Windows: set event loop policy before starting
uvicorn main:app --reload
# On Windows use: watchfiles "uvicorn main:app"  (avoids reload + Playwright conflict)

# Frontend
cd frontend
npm install
npm run dev

# Simple agent (Level 2, run separately)
cd agent
pip install openai httpx
BACKEND_URL=http://localhost:8000 python simple_agent.py "your query here"
```
