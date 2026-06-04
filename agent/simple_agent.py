"""Level 2 built-in agent — OpenAI-compatible tool-calling loop."""

from __future__ import annotations

import json
import os
import sys
import time

import httpx
from openai import OpenAI

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

SYSTEM_PROMPT = """You are a lead generation agent. Given a target description:
1. Call scrape_leads with a clear query and sources [google, company, linkedin].
2. Poll get_job until status is done or failed.
3. Call get_leads and summarize the best matches with relevance notes.
Assign mental relevance scores when summarizing."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scrape_leads",
            "description": "Start a lead generation scrape. Returns job_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Subset of google, company, linkedin",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job",
            "description": "Poll scrape job status.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_leads",
            "description": "Retrieve collected leads.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_score": {"type": "number"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
]


def call_tool(name: str, args: dict) -> dict | list:
    with httpx.Client(base_url=BACKEND, timeout=60.0) as http:
        if name == "scrape_leads":
            r = http.post("/scrape", json=args)
            r.raise_for_status()
            return r.json()
        if name == "get_job":
            r = http.get(f"/jobs/{args['job_id']}")
            r.raise_for_status()
            return r.json()
        if name == "get_leads":
            r = http.get("/leads", params=args)
            r.raise_for_status()
            return r.json()
    raise ValueError(f"Unknown tool: {name}")


def run(user_query: str) -> None:
    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY", "ollama"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]

    for _ in range(20):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            print(msg.content or "")
            return

        for tc in msg.tool_calls:
            fn = tc.function
            args = json.loads(fn.arguments or "{}")
            result = call_tool(fn.name, args)

            if fn.name == "scrape_leads" and isinstance(result, dict) and result.get("job_id"):
                job_id = result["job_id"]
                for _ in range(60):
                    job = call_tool("get_job", {"job_id": job_id})
                    status = job.get("status") if isinstance(job, dict) else None
                    if status in ("done", "failed"):
                        result = {"job": job, "note": "polled until terminal"}
                        break
                    time.sleep(2)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )

    print("Agent stopped after max tool rounds.")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or input("Target description: ").strip()
    if not q:
        print("No query provided.")
        sys.exit(1)
    run(q)
