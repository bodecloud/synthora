import { useCallback, useEffect, useState } from "react";
import { api, RunSummary } from "../api";

export interface ChatTurn {
  runId: string;
  question: string;
  status: string;
  report: string | null;
}

export function Chat({
  sessionId,
  onSessionId,
  onStarted,
}: {
  sessionId: string;
  onSessionId: (id: string) => void;
  onStarted: (runId: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  const refreshTranscript = useCallback(async (sid: string) => {
    if (!sid) {
      setTurns([]);
      return;
    }
    const runs = await api.listRuns(sid);
    const ordered = [...runs].sort((a, b) =>
      a.created_at.localeCompare(b.created_at),
    );
    const next: ChatTurn[] = [];
    for (const run of ordered) {
      let report: string | null = null;
      if (run.status === "completed") {
        try {
          const r = await api.getReport(run.id);
          report = r.report_markdown;
        } catch {
          report = null;
        }
      }
      next.push({
        runId: run.id,
        question: run.question,
        status: run.status,
        report,
      });
    }
    setTurns(next);
  }, []);

  useEffect(() => {
    refreshTranscript(sessionId).catch((e) => setError(String(e)));
  }, [sessionId, refreshTranscript]);

  async function send() {
    if (!message.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.chat(message.trim(), sessionId || null);
      onSessionId(result.session_id);
      setMessage("");
      await refreshTranscript(result.session_id);
      onStarted(result.run_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function openRun(run: RunSummary | ChatTurn) {
    const id = "runId" in run ? run.runId : run.id;
    onStarted(id);
  }

  return (
    <section className="panel">
      <h2>Chat research</h2>
      <p className="muted">
        Multi-turn research on one session. Each message starts a{" "}
        <code>fast_research</code> run that sees prior reports in that session.
      </p>
      {error && <p className="error-text">{error}</p>}
      {sessionId && (
        <p className="muted">
          Session <code>{sessionId}</code>
          <button
            className="ghost"
            type="button"
            style={{ marginLeft: "0.5rem" }}
            onClick={() => {
              onSessionId("");
              setTurns([]);
            }}
          >
            New session
          </button>
        </p>
      )}

      {turns.length > 0 && (
        <ol className="discourse-list">
          {turns.map((t) => (
            <li key={t.runId} className="discourse-turn">
              <div className="discourse-meta">
                <strong>You</strong>
                <span className="muted">
                  {" "}
                  · <span className={`status-badge status-${t.status}`}>{t.status}</span>
                </span>
                <button
                  className="ghost"
                  type="button"
                  style={{ marginLeft: "0.5rem" }}
                  onClick={() => openRun(t)}
                >
                  Open run
                </button>
              </div>
              <p>{t.question}</p>
              {t.report && (
                <details>
                  <summary>Report</summary>
                  <pre className="report-snippet">{t.report.slice(0, 2000)}</pre>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}

      <div className="steer-row">
        <input
          type="text"
          placeholder="Ask a question…"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          aria-label="chat message"
        />
        <button
          className="primary"
          type="button"
          disabled={busy || !message.trim()}
          onClick={send}
        >
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
    </section>
  );
}
