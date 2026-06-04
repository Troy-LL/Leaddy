# LeadGen Harness

Find business leads from a plain-English search — and watch them appear in a live dashboard as they’re discovered.

You might type something like *“CTOs at Series A fintech startups in Southeast Asia”*. The system searches the web, visits company sites, optionally enriches from LinkedIn, saves everything to a local database, and streams new rows to your browser in real time.

**You do not need OpenClaw, Hermes, or a powerful GPU to get started.** The simplest path is Docker + the built-in dashboard.

---

## What you get

| Piece | What it does |
|--------|----------------|
| **Dashboard** | Search box, live feed, filterable table, CSV export |
| **API** | Start scrapes, check job status, list leads, WebSocket stream |
| **Scrapers** | Google discovery → company pages → optional LinkedIn |
| **Agent (optional)** | Smarter query breakdown and result ranking |

---

## Pick your setup (3 levels)

Choose one — you can stay on Level 1 forever if you want.

### Level 1 — Dashboard only (easiest)

**You need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose).

No API keys. No AI agent. Just search and scrape from the UI.

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:5173**, type a query, click **Scrape**. Leads show up in the table and live feed as they’re found.

---

### Level 2 — Built-in AI agent (recommended if you want “smarter” searches)

Same as Level 1, plus a small Python agent that talks to your LLM and calls the API for you.

**You need:** Level 1 requirements **plus** one of:

- An [OpenAI](https://platform.openai.com/) API key, or  
- A local model via [Ollama](https://ollama.com/) (free, runs on your machine)

```bash
cp .env.example .env
# Edit .env — set LLM_API_KEY and optionally LLM_BASE_URL / LLM_MODEL

docker compose --profile simple-agent up --build
```

**Using Ollama (free, local):**

1. Install Ollama and pull a model, e.g. `ollama pull llama3`
2. In `.env` set:
   ```env
   LLM_API_KEY=ollama
   LLM_BASE_URL=http://host.docker.internal:11434/v1
   LLM_MODEL=llama3
   ```
3. Run the compose command above

The simple agent container starts with the stack. You can also run it by hand:

```bash
cd agent
pip install openai httpx
set BACKEND_URL=http://localhost:8000
python simple_agent.py "find marketing directors at B2B SaaS companies in the UK"
```

---

### Level 3 — OpenClaw or Hermes (if you already use those)

For people who already run [OpenClaw](https://github.com/openclaw/openclaw) or Hermes and want to plug in this project’s tools.

```bash
docker compose --profile openclaw up --build
# or
docker compose --profile hermes up --build
```

Tool definitions and prompts live in [`agent/skill.md`](agent/skill.md). The Docker images for Level 3 are stubs — point your existing runtime at that skill file, or extend the Dockerfiles in `agent/`.

Optional: Scrapling’s official OpenClaw skill:

```bash
clawhub install scrapling-official
```

---

## Quick reference

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | React dashboard |
| http://localhost:8000/docs | API docs (Swagger) |
| http://localhost:8000/health | API health check |

**Stop everything:** `Ctrl+C` in the terminal where Compose is running.

**Start fresh (keeps your lead database):** `docker compose down` then `docker compose up` again.

**Wipe stored leads:** `docker compose down -v` (removes the `leads_data` volume).

---

## How it works (simple version)

```text
Your search
    │
    ├─► Dashboard ──► API starts a scrape job
    │
    └─► (Optional) Agent ──► same API, smarter steps
              │
              ▼
        Google → company websites → LinkedIn (if configured)
              │
              ▼
        SQLite database  +  live WebSocket updates to the UI
```

Heavy browser work runs in a separate **Scrapling** container (`scrapling_mcp`), so the main API stays light and fast to build.

---

## Optional configuration

Copy `.env.example` to `.env` and fill in only what you need.

| Variable | Required? | What it does |
|----------|-----------|----------------|
| `LI_AT` | No | LinkedIn session cookie — enables LinkedIn enrichment. Without it, Google + company scraping still run. |
| `GOOGLE_SERP_KEY` | No | Paid search API (future use). Default uses direct HTTP search. |
| `LLM_API_KEY` | Level 2 only | Your LLM provider key |
| `LLM_BASE_URL` | Level 2 only | API base URL (OpenAI, Anthropic, Ollama, etc.) |
| `LLM_MODEL` | Level 2 only | Model name, e.g. `gpt-4o-mini` or `llama3` |

**LinkedIn cookie (`LI_AT`):** In Chrome, log into LinkedIn → DevTools → Application → Cookies → `www.linkedin.com` → copy `li_at`. Use only for personal/research use; scraping may violate LinkedIn’s terms.

---

## Run without Docker (developers)

**Terminal 1 — Scrapling MCP** (needed for company/LinkedIn browser fetches):

```bash
docker run -p 8001:8001 pyd4vinci/scrapling scrapling mcp --http --host 0.0.0.0 --port 8001
```

**Terminal 2 — API:**

```bash
cd backend
pip install -r requirements.txt
# Windows: use watchfiles if you need reload — see PLAN.md
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 3 — Dashboard:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

---

## Project layout

```text
leadgen-harness/
├── README.md              ← you are here
├── PLAN.md                ← full technical blueprint
├── docker-compose.yml
├── backend/               ← FastAPI + scrapers + SQLite
├── frontend/              ← React dashboard
├── agent/                 ← simple agent + skill manifest
└── tests/                 ← API smoke tests
```

---

## Troubleshooting

**Dashboard can’t reach the API (CORS or network errors)**  
Make sure the backend is up on port 8000. The frontend proxies `/api` to the backend when using `npm run dev`.

**No leads appearing**  
- First scrape can take a minute while pages are fetched.  
- Check job status in the UI (job badge) or `GET http://localhost:8000/jobs/{job_id}`.  
- Google may rate-limit heavy use; try a simpler query or add `GOOGLE_SERP_KEY` later.

**LinkedIn step does nothing**  
Expected if `LI_AT` is empty. Add the cookie to `.env` and restart Compose.

**`scrapling_mcp` slow on first run**  
Docker pulls a large official image with browsers pre-installed. That’s normal; later starts are faster.

**Windows + hot reload issues**  
If Playwright or reload causes errors, run without `--reload` or use `watchfiles` — details in [PLAN.md](PLAN.md).

---

## Tests

With the API running on port 8000:

```bash
pip install -r tests/requirements.txt
pytest tests/test_api.py -v
```

---

## More detail

Architecture, risks, and build decisions are documented in [PLAN.md](PLAN.md).

Scraping is powered by [Scrapling](https://github.com/D4Vinci/Scrapling). Use responsibly: respect `robots.txt`, site terms, and privacy laws.

---

## License

Components follow their upstream licenses (Scrapling: BSD-3-Clause). Add a project license file if you distribute this repo.
