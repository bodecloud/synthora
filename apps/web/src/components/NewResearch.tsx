import { useEffect, useState } from "react";
import {
  api,
  PipelineSpec,
  Providers,
  ResearchConfig,
  SessionSummary,
} from "../api";

export function NewResearch({
  onStarted,
}: {
  onStarted: (runId: string) => void;
}) {
  const [pipelines, setPipelines] = useState<PipelineSpec[]>([]);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [pipelineId, setPipelineId] = useState("deep_research");
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [engines, setEngines] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("");
  const [allowClarification, setAllowClarification] = useState(false);
  const [plannerModel, setPlannerModel] = useState("");
  const [researcherModel, setResearcherModel] = useState("");
  const [writerModel, setWriterModel] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpToken, setMcpToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPipelines().then(setPipelines).catch((e) => setError(String(e)));
    api
      .listProviders()
      .then((p) => {
        setProviders(p);
        if (p.search_engines.length && engines.length === 0) {
          const preferred = ["searxng", "collection", "duckduckgo", "ddg"];
          const pick =
            preferred.find((id) => p.search_engines.includes(id)) ||
            p.search_engines[0];
          setEngines([pick]);
        }
        if (p.search_strategies.length && !strategy) {
          setStrategy(p.search_strategies[0]);
        }
      })
      .catch(() => {
        /* providers optional for start */
      });
    api.listSessions().then(setSessions).catch(() => {
      /* sessions require auth */
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggleEngine(id: string) {
    setEngines((prev) =>
      prev.includes(id) ? prev.filter((e) => e !== id) : [...prev, id],
    );
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const config: ResearchConfig = {
        allow_clarification: allowClarification,
      };
      if (engines.length) config.search_engines = engines;
      if (strategy) config.search_strategy = strategy;
      if (plannerModel.trim()) config.planner_model = plannerModel.trim();
      if (researcherModel.trim())
        config.researcher_model = researcherModel.trim();
      if (writerModel.trim()) config.writer_model = writerModel.trim();
      if (mcpUrl.trim()) {
        const server: Record<string, string> = {
          url: mcpUrl.trim(),
          transport: "http",
        };
        if (mcpToken.trim()) server.token = mcpToken.trim();
        config.extra = {
          ...(config.extra as Record<string, unknown> | undefined),
          mcp: { servers: [server] },
        };
      }

      const { run_id } = await api.startResearch(question.trim(), pipelineId, {
        session_id: sessionId || null,
        config,
      });
      onStarted(run_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Ask a research question</h2>
      <textarea
        placeholder="What would you like to understand deeply?"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        aria-label="research question"
      />

      <div className="pipeline-grid" role="radiogroup" aria-label="pipeline">
        {pipelines.map((p) => (
          <div
            key={p.id}
            role="radio"
            aria-checked={pipelineId === p.id}
            tabIndex={0}
            className={`pipeline-option ${pipelineId === p.id ? "selected" : ""}`}
            onClick={() => setPipelineId(p.id)}
            onKeyDown={(e) => e.key === "Enter" && setPipelineId(p.id)}
          >
            <h3>{p.name}</h3>
            <p>{p.description}</p>
          </div>
        ))}
      </div>

      <div className="config-grid">
        <label className="field">
          Session
          <select
            aria-label="session"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
          >
            <option value="">None (standalone run)</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          New session title
          <div className="steer-row">
            <input
              type="text"
              placeholder="Optional — create then select"
              value={newSessionTitle}
              onChange={(e) => setNewSessionTitle(e.target.value)}
              aria-label="new session title"
            />
            <button
              type="button"
              className="ghost"
              disabled={!newSessionTitle.trim()}
              onClick={async () => {
                try {
                  const created = await api.createSession(newSessionTitle.trim());
                  setSessions((prev) => [created, ...prev]);
                  setSessionId(created.id);
                  setNewSessionTitle("");
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              Create
            </button>
          </div>
        </label>

        <label className="field">
          Search strategy
          <select
            aria-label="search strategy"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            {(providers?.search_strategies ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {providers && providers.search_engines.length > 0 && (
        <fieldset className="engine-fieldset">
          <legend>Search engines</legend>
          <div className="chip-row" role="group" aria-label="search engines">
            {providers.search_engines.map((eng) => (
              <label key={eng} className="chip">
                <input
                  type="checkbox"
                  checked={engines.includes(eng)}
                  onChange={() => toggleEngine(eng)}
                />
                {eng}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <label className="check-row">
        <input
          type="checkbox"
          checked={allowClarification}
          onChange={(e) => setAllowClarification(e.target.checked)}
          aria-label="allow clarification"
        />
        Allow clarification questions before research
      </label>

      <details className="model-details">
        <summary>Optional model overrides</summary>
        <div className="config-grid">
          <label className="field">
            Planner model
            <input
              type="text"
              placeholder="e.g. openai:gpt-4o-mini"
              value={plannerModel}
              onChange={(e) => setPlannerModel(e.target.value)}
              aria-label="planner model"
            />
          </label>
          <label className="field">
            Researcher model
            <input
              type="text"
              placeholder="e.g. openai:gpt-4o-mini"
              value={researcherModel}
              onChange={(e) => setResearcherModel(e.target.value)}
              aria-label="researcher model"
            />
          </label>
          <label className="field">
            Writer model
            <input
              type="text"
              placeholder="e.g. openai:gpt-4o"
              value={writerModel}
              onChange={(e) => setWriterModel(e.target.value)}
              aria-label="writer model"
            />
          </label>
        </div>
      </details>

      <details className="model-details">
        <summary>Optional MCP tools</summary>
        <p className="muted">
          Load tools from an MCP HTTP server into researchers for this run.
        </p>
        <div className="config-grid">
          <label className="field">
            MCP server URL
            <input
              type="text"
              placeholder="http://127.0.0.1:8000"
              value={mcpUrl}
              onChange={(e) => setMcpUrl(e.target.value)}
              aria-label="mcp server url"
            />
          </label>
          <label className="field">
            Bearer token
            <input
              type="password"
              placeholder="optional"
              value={mcpToken}
              onChange={(e) => setMcpToken(e.target.value)}
              aria-label="mcp bearer token"
            />
          </label>
        </div>
      </details>

      {error && <p className="error-text">{error}</p>}
      <button
        className="primary"
        disabled={busy || question.trim().length < 3}
        onClick={start}
      >
        {busy ? "Starting…" : "Start research"}
      </button>
    </section>
  );
}
