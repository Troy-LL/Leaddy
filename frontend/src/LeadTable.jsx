import { useMemo, useState } from "react";

function toCsv(rows) {
  const headers = ["id", "name", "email", "company", "title", "source", "url", "score"];
  const lines = [
    headers.join(","),
    ...rows.map((r) =>
      headers
        .map((h) => {
          const v = r[h] ?? "";
          const s = String(v).replace(/"/g, '""');
          return `"${s}"`;
        })
        .join(",")
    ),
  ];
  return lines.join("\n");
}

export default function LeadTable({ leads }) {
  const [companyFilter, setCompanyFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [minScore, setMinScore] = useState(0);

  const filtered = useMemo(() => {
    return leads.filter((l) => {
      if (companyFilter && !(l.company || "").toLowerCase().includes(companyFilter.toLowerCase())) {
        return false;
      }
      if (sourceFilter && l.source !== sourceFilter) {
        return false;
      }
      if ((l.score ?? 0) < minScore) {
        return false;
      }
      return true;
    });
  }, [leads, companyFilter, sourceFilter, minScore]);

  const exportCsv = () => {
    const blob = new Blob([toCsv(filtered)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="table-panel">
      <div className="table-toolbar">
        <input
          placeholder="Filter company"
          value={companyFilter}
          onChange={(e) => setCompanyFilter(e.target.value)}
        />
        <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
          <option value="">All sources</option>
          <option value="google">google</option>
          <option value="company">company</option>
          <option value="linkedin">linkedin</option>
        </select>
        <label>
          Min score: {minScore.toFixed(1)}
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={minScore}
            onChange={(e) => setMinScore(parseFloat(e.target.value))}
          />
        </label>
        <button type="button" onClick={exportCsv}>
          Export CSV
        </button>
        <span className="muted">{filtered.length} leads</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Company</th>
              <th>Title</th>
              <th>Source</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((lead) => (
              <tr key={lead.id}>
                <td>{lead.name || "—"}</td>
                <td>{lead.email || "—"}</td>
                <td>{lead.company || "—"}</td>
                <td>{lead.title || "—"}</td>
                <td>{lead.source}</td>
                <td>{lead.score != null ? Number(lead.score).toFixed(2) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
