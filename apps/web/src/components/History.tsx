import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { api, RunSummary } from "../api";

export function History({ onOpen }: { onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .listRuns()
      .then(setRuns)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(runId: string, e: MouseEvent) {
    e.stopPropagation();
    if (!window.confirm("Delete this research run?")) return;
    try {
      await api.deleteRun(runId);
      setRuns((prev) => prev.filter((r) => r.id !== runId));
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleClearAll() {
    if (!window.confirm("Delete ALL research runs in this workspace?")) return;
    setBusy(true);
    setError(null);
    try {
      await api.clearHistory();
      setRuns([]);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="action-row">
        <h2 style={{ margin: 0, flex: 1 }}>Research history</h2>
        {runs.length > 0 && (
          <button
            type="button"
            className="ghost danger"
            disabled={busy}
            onClick={handleClearAll}
          >
            Clear all
          </button>
        )}
      </div>
      {error && <p className="error-text">{error}</p>}
      {runs.length === 0 && !error && <p>No research yet.</p>}
      {runs.length > 0 && (
        <table className="runs">
          <thead>
            <tr>
              <th>Question</th>
              <th>Pipeline</th>
              <th>Session</th>
              <th>Status</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} onClick={() => onOpen(r.id)}>
                <td>{r.question}</td>
                <td>
                  <code>{r.pipeline_id}</code>
                </td>
                <td>
                  {r.session_id ? (
                    <code title={r.session_id}>
                      {r.session_id.slice(0, 8)}…
                    </code>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  <span className={`status-badge status-${r.status}`}>
                    {r.status}
                  </span>
                </td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <button
                    type="button"
                    className="ghost danger"
                    aria-label={`delete ${r.question}`}
                    onClick={(e) => handleDelete(r.id, e)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
