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
  const [engines, setEngines] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("");
  const [allowClarification, setAllowClarification] = useState(false);
  const [plannerModel, setPlannerModel] = useState("");
  const [researcherModel, setResearcherModel] = useState("");
  const [writerModel, setWriterModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPipelines().then(setPipelines).catch((e) => setError(String(e)));
    api
      .listProviders()
      .then((p) => {
        setProviders(p);
        if (p.search_engines.length && engines.length === 0) {
          setEngines([p.search_engines[0]]);
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
