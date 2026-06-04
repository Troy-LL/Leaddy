import { useCallback, useEffect, useState } from "react";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname}:8000/stream`;

const MAX_LIVE = 50;
const MAX_RETRIES = 5;

export default function LeadFeed({ onLead }) {
  const [liveLeads, setLiveLeads] = useState([]);
  const [status, setStatus] = useState("connecting");

  const connect = useCallback(() => {
    let retries = 0;
    let ws;
    let closed = false;

    const attempt = () => {
      if (closed) return;
      setStatus(retries === 0 ? "connecting" : "reconnecting");
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        retries = 0;
        setStatus("live");
      };

      ws.onmessage = (event) => {
        try {
          const lead = JSON.parse(event.data);
          setLiveLeads((prev) => [lead, ...prev].slice(0, MAX_LIVE));
          onLead?.(lead);
        } catch {
          /* ignore malformed */
        }
      };

      ws.onclose = () => {
        if (closed) return;
        if (retries >= MAX_RETRIES) {
          setStatus("disconnected");
          return;
        }
        const delay = Math.min(16000, 1000 * 2 ** retries);
        retries += 1;
        setTimeout(attempt, delay);
      };

      ws.onerror = () => ws.close();
    };

    attempt();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [onLead]);

  useEffect(() => connect(), [connect]);

  return (
    <aside className="feed">
      <div className="feed-header">
        <h2>Live feed</h2>
        <span className={`badge badge-${status}`}>{status}</span>
      </div>
      <ul className="feed-list">
        {liveLeads.length === 0 && (
          <li className="feed-empty">Waiting for leads…</li>
        )}
        {liveLeads.map((lead) => (
          <li key={lead.id} className="feed-item">
            <strong>{lead.name || lead.company || "Unknown"}</strong>
            <span className="muted">{lead.source}</span>
            {lead.email && <div>{lead.email}</div>}
          </li>
        ))}
      </ul>
    </aside>
  );
}
