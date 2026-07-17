import { useState } from "react";
import { api } from "../api";

export function Chat({
  onStarted,
}: {
  onStarted: (runId: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);

  async function send() {
    if (!message.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.chat(message.trim(), sessionId || null);
      setSessionId(result.session_id);
      setLastRunId(result.run_id);
      setMessage("");
      onStarted(result.run_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Chat research</h2>
      <p className="muted">
        Sends your message as a <code>fast_research</code> run. Replies stay on
        the same session when you keep chatting.
      </p>
      {error && <p className="error-text">{error}</p>}
      {sessionId && (
        <p className="muted">
          Session <code>{sessionId}</code>
          {lastRunId && (
            <>
              {" "}
              · last run <code>{lastRunId}</code>
            </>
          )}
        </p>
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
