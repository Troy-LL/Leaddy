import { useCallback, useEffect, useMemo, useState } from "react";
import LeadFeed from "./LeadFeed.jsx";
import LeadTable from "./LeadTable.jsx";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "/api";

export default function App() {
  const [query, setQuery] = useState("");
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const mergeLead = useCallback((lead) => {
    setLeads((prev) => {
      const map = new Map(prev.map((l) => [l.id, l]));
      map.set(lead.id, { ...map.get(lead.id), ...lead });
      return Array.from(map.values()).sort((a, b) =>
        (b.created_at || "").localeCompare(a.created_at || "")
      );
    });
  }, []);

  const fetchLeads = useCallback(async () => {
    const res = await fetch(`${API}/leads?limit=500`);
    if (!res.ok) throw new Error("Failed to load leads");
    const data = await res.json();
    setLeads((prev) => {
      const map = new Map(prev.map((l) => [l.id, l]));
      for (const lead of data) {
        map.set(lead.id, { ...map.get(lead.id), ...lead });
      }
      return Array.from(map.values());
    });
  }, []);

  useEffect(() => {
    fetchLeads().catch(() => setError("Could not load leads from API"));
  }, [fetchLeads]);

  useEffect(() => {
    if (!jobId || jobStatus === "done" || jobStatus === "failed") return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`${API}/jobs/${jobId}`);
        if (res.ok) {
          const job = await res.json();
          setJobStatus(job.status);
          if (job.status === "done") {
            await fetchLeads();
          }
        }
      } catch {
        /* ignore poll errors */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [jobId, jobStatus, fetchLeads]);

  const startScrape = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/scrape`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query.trim(),
          sources: ["google", "company", "linkedin"],
        }),
      });
      if (!res.ok) throw new Error("Scrape request failed");
      const data = await res.json();
      setJobId(data.job_id);
      setJobStatus(data.status || "queued");
    } catch (e) {
      setError(e.message || "Scrape failed");
    } finally {
      setLoading(false);
    }
  };

  const statusLabel = useMemo(() => {
    if (!jobId) return null;
    return `Job ${jobId.slice(0, 8)}… — ${jobStatus || "…"}`;
  }, [jobId, jobStatus]);

  return (
    <div className="app">
      <header className="header">
        <h1>LeadGen Harness</h1>
        <p className="muted">Level 1: search directly — no external agent required</p>
        <div className="search-row">
          <input
            className="search-input"
            placeholder='e.g. "CTOs at Series A fintech startups in Southeast Asia"'
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && startScrape()}
          />
          <button type="button" onClick={startScrape} disabled={loading}>
            {loading ? "Starting…" : "Scrape"}
          </button>
        </div>
        {statusLabel && <div className="job-status">{statusLabel}</div>}
        {error && <div className="error">{error}</div>}
      </header>
      <main className="layout">
        <LeadFeed onLead={mergeLead} />
        <LeadTable leads={leads} />
      </main>
    </div>
  );
}
