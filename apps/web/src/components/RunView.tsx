import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  api,
  Citation,
  DiscourseTurn,
  downloadExport,
  KnowledgeEdge,
  KnowledgeNode,
  RunDetail,
  RunMetrics,
  TERMINAL_STATUSES,
} from "../api";
import { useRunEvents } from "../hooks/useRunEvents";
import { EventFeed } from "./EventFeed";
import { KnowledgeMapView } from "./KnowledgeMapView";

export function RunView({
  runId,
  onDeleted,
  onFollowup,
}: {
  runId: string;
  onDeleted?: () => void;
  onFollowup?: (runId: string) => void;
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [discourse, setDiscourse] = useState<DiscourseTurn[]>([]);
  const [kmap, setKmap] = useState<{
    nodes: KnowledgeNode[];
    edges: KnowledgeEdge[];
  } | null>(null);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [steer, setSteer] = useState("");
  const [clarifyAnswer, setClarifyAnswer] = useState("");
  const [followup, setFollowup] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { events, finished, statusTick } = useRunEvents(runId);

  const refresh = useCallback(async () => {
    const detail = await api.getRun(runId);
    setRun(detail);
    try {
      const turns = await api.getDiscourse(runId);
      setDiscourse(turns);
    } catch {
      /* discourse optional */
    }
    if (detail.status === "completed") {
      try {
        const r = await api.getReport(runId);
        setReport(r.report_markdown);
        setCitations(r.citations);
      } catch {
        /* report may not exist for cancelled runs */
      }
      try {
        const m = await api.getKnowledgeMap(runId);
        if (m.nodes.length) setKmap(m);
      } catch {
        /* knowledge map optional */
      }
      try {
        const metrics = await api.getRunMetrics(runId);
        setMetrics(metrics);
      } catch {
        /* metrics optional */
      }
    }
  }, [runId]);

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh, finished, statusTick]);

  const awaitingInput = run?.status === "awaiting_input";
  const clarifyQuestion =
    [...events]
      .reverse()
      .find((e) => e.type === "interrupt")?.message ||
    [...events]
      .reverse()
      .find((e) => e.type === "interrupt")?.payload?.question;
  const running =
    run != null &&
    !TERMINAL_STATUSES.includes(run.status) &&
    !awaitingInput;

  async function submitClarification() {
    if (!clarifyAnswer.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.resumeResearch(runId, clarifyAnswer.trim());
      setClarifyAnswer("");
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Delete this research run?")) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteRun(runId);
      onDeleted?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(format: "markdown" | "html" | "pdf") {
    setError(null);
    try {
      await downloadExport(runId, format);
    } catch (e) {
      setError(String(e));
    }
  }

  async function submitFollowup() {
    if (!followup.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.followupResearch(runId, followup.trim());
      setFollowup("");
      onFollowup?.(result.run_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <h2>{run?.question ?? "Loading…"}</h2>
        {run && (
          <p>
            <span className={`status-badge status-${run.status}`}>
              {run.status}
            </span>{" "}
            <code>{run.pipeline_id}</code>
            {run.session_id && (
              <>
                {" "}
                · session <code>{run.session_id}</code>
              </>
            )}
          </p>
        )}
        {run?.brief && <p>{run.brief}</p>}
        {run?.error && <p className="error-text">{run.error}</p>}
        {error && <p className="error-text">{error}</p>}

        <div className="action-row">
          <button
            className="ghost"
            type="button"
            onClick={() => handleExport("markdown")}
          >
            Export Markdown
          </button>
          <button
            className="ghost"
            type="button"
            onClick={() => handleExport("html")}
          >
            Export HTML
          </button>
          <button
            className="ghost"
            type="button"
            onClick={() => handleExport("pdf")}
          >
            Export PDF
          </button>
          <button
            className="ghost danger"
            type="button"
            disabled={busy}
            onClick={handleDelete}
          >
            Delete run
          </button>
        </div>

        {metrics && (
          <p className="muted">
            Metrics: {metrics.llm_calls} LLM calls · {metrics.search_calls}{" "}
            searches · {metrics.prompt_chars + metrics.completion_chars} chars
          </p>
        )}

        {awaitingInput && (
          <div className="clarify-box">
            <h3>Clarification needed</h3>
            <p>
              {typeof clarifyQuestion === "string" && clarifyQuestion
                ? clarifyQuestion
                : "The pipeline is waiting for your answer before continuing."}
            </p>
            <div className="steer-row">
              <input
                type="text"
                placeholder="Your clarification answer"
                value={clarifyAnswer}
                onChange={(e) => setClarifyAnswer(e.target.value)}
                aria-label="clarification answer"
              />
              <button
                className="primary"
                type="button"
                disabled={busy || !clarifyAnswer.trim()}
                onClick={submitClarification}
              >
                {busy ? "Submitting…" : "Resume"}
              </button>
            </div>
          </div>
        )}

        {running && (
          <>
            <button
              className="ghost"
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await api.cancelRun(runId);
                  await refresh();
                } catch (e) {
                  setError(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Cancel run
            </button>
            <div className="steer-row">
              <input
                type="text"
                placeholder="Steer the research (e.g. 'focus on costs')"
                value={steer}
                onChange={(e) => setSteer(e.target.value)}
                aria-label="steering message"
              />
              <button
                className="primary"
                type="button"
                disabled={busy || !steer.trim()}
                onClick={async () => {
                  const msg = steer.trim();
                  if (!msg) return;
                  setBusy(true);
                  setError(null);
                  try {
                    await api.steerRun(runId, msg);
                    setSteer("");
                    await refresh();
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Steer
              </button>
            </div>
          </>
        )}

        {run?.status === "completed" && (
          <div className="steer-row" style={{ marginTop: "1rem" }}>
            <input
              type="text"
              placeholder="Ask a follow-up question…"
              value={followup}
              onChange={(e) => setFollowup(e.target.value)}
              aria-label="follow-up question"
            />
            <button
              className="primary"
              type="button"
              disabled={busy || !followup.trim()}
              onClick={submitFollowup}
            >
              Follow up
            </button>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Progress</h2>
        <EventFeed events={events} />
      </section>

      {discourse.length > 0 && (
        <section className="panel">
          <h2>Discourse</h2>
          <ol className="discourse-list">
            {discourse.map((t) => (
              <li key={t.id} className="discourse-turn">
                <div className="discourse-meta">
                  <strong>{t.speaker}</strong>
                  <span className="muted">
                    {" "}
                    · {t.role} · {t.intent}
                  </span>
                </div>
                <p>{t.utterance}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {report && (
        <section className="panel">
          <h2>Report</h2>
          <div className="report-body">
            <ReactMarkdown>{report}</ReactMarkdown>
          </div>
          {citations.length > 0 && (
            <details>
              <summary>{citations.length} citations</summary>
              <ol>
                {citations
                  .filter((c) => c.index != null)
                  .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
                  .map((c) => (
                    <li key={c.id} value={c.index ?? undefined}>
                      <a href={c.url} target="_blank" rel="noreferrer">
                        {c.title || c.url}
                      </a>
                      {!c.verified && " (unverified)"}
                    </li>
                  ))}
              </ol>
            </details>
          )}
        </section>
      )}

      {kmap && (
        <section className="panel">
          <h2>Knowledge map</h2>
          <KnowledgeMapView nodes={kmap.nodes} edges={kmap.edges} />
        </section>
      )}
    </>
  );
}
