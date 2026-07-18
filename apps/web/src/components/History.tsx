import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { api, RunSummary, SessionSummary } from "../api";

export function History({ onOpen }: { onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRuns = useCallback((sessionFilter?: string | null) => {
    const filter =
      sessionFilter !== undefined ? sessionFilter : selectedSessionId;
    api
      .listRuns(filter || undefined)
      .then(setRuns)
      .catch((e) => setError(String(e)));
  }, [selectedSessionId]);

  const loadSessions = useCallback(() => {
    api
      .listSessions()
      .then(setSessions)
      .catch(() => {
        /* sessions optional when auth is off / unavailable */
      });
  }, []);

  useEffect(() => {
    loadRuns();
    loadSessions();
  }, [loadRuns, loadSessions]);

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

  async function handleDeleteSession(sessionId: string) {
    if (
      !window.confirm(
        "Delete this session? Runs keep their history but lose the session link display.",
      )
    ) {
      return;
    }
    try {
      await api.deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null);
        loadRuns(null);
      }
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

  async function handleSelectSession(sessionId: string) {
    setError(null);
    if (selectedSessionId === sessionId) {
      setSelectedSessionId(null);
      loadRuns(null);
      return;
    }
    setSelectedSessionId(sessionId);
    try {
      const detail = await api.getSession(sessionId);
      setRuns(detail.runs);
    } catch (err) {
      setError(String(err));
    }
  }

  function sessionTitle(id: string | null): string {
    if (!id) return "—";
    const match = sessions.find((s) => s.id === id);
    return match?.title || `${id.slice(0, 8)}…`;
  }

  return (
    <section className="panel">
      <div className="action-row">
        <h2 style={{ margin: 0, flex: 1 }}>Research history</h2>
        {selectedSessionId && (
          <button
            type="button"
            className="ghost"
            onClick={() => {
              setSelectedSessionId(null);
              loadRuns(null);
            }}
          >
            Clear session filter
          </button>
        )}
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
      {selectedSessionId && (
        <p className="muted">
          Showing runs for session:{" "}
          <strong>{sessionTitle(selectedSessionId)}</strong>
        </p>
      )}
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
                    <span title={r.session_id}>{sessionTitle(r.session_id)}</span>
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

      {sessions.length > 0 && (
        <>
          <h2>Sessions</h2>
          <ul className="discourse-list">
            {sessions.map((s) => (
              <li key={s.id} className="discourse-turn">
                <div className="discourse-meta">
                  <button
                    type="button"
                    className="ghost"
                    aria-pressed={selectedSessionId === s.id}
                    onClick={() => handleSelectSession(s.id)}
                  >
                    <strong>{s.title}</strong>
                  </button>
                  <span className="muted">
                    {" "}
                    · <code>{s.id.slice(0, 8)}…</code>
                  </span>
                  <button
                    type="button"
                    className="ghost danger"
                    style={{ marginLeft: "0.5rem" }}
                    onClick={() => handleDeleteSession(s.id)}
                  >
                    Delete session
                  </button>
                </div>
                {s.tags?.length ? (
                  <p className="muted">{s.tags.join(", ")}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
