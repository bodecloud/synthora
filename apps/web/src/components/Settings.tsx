import { FormEvent, useEffect, useState } from "react";
import { api, Providers } from "../api";

const EDITABLE_KEYS = [
  "openai",
  "anthropic",
  "openrouter",
  "ollama",
  "tavily",
  "brave",
  "searxng",
] as const;

type SettingMap = Record<string, Record<string, unknown>>;

export function Settings() {
  const [providers, setProviders] = useState<Providers | null>(null);
  const [settings, setSettings] = useState<SettingMap>({});
  const [selected, setSelected] = useState<string>("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.listProviders(), api.listSettings()])
      .then(([prov, rows]) => {
        setProviders(prov);
        const map: SettingMap = {};
        for (const row of rows) {
          map[row.key] = row.value || {};
        }
        setSettings(map);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    const current = settings[selected] || {};
    setApiKey(String(current.api_key || current.key || ""));
    setBaseUrl(String(current.base_url || current.url || ""));
  }, [selected, settings]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const value: Record<string, unknown> = {
        ...(settings[selected] || {}),
      };
      if (apiKey.trim()) {
        value.api_key = apiKey.trim();
      } else {
        delete value.api_key;
        delete value.key;
      }
      if (baseUrl.trim()) {
        value.base_url = baseUrl.trim();
      } else {
        delete value.base_url;
        delete value.url;
      }
      const saved = await api.putSetting(selected, value);
      setSettings((prev) => ({ ...prev, [selected]: saved.value }));
      setMessage(`Saved settings for ${selected}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel">
      <h2>Provider settings</h2>
      {error && <p className="error-text">{error}</p>}
      {message && <p className="muted">{message}</p>}

      <form className="settings-form" onSubmit={onSave}>
        <label>
          Provider / engine
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            aria-label="provider key"
          >
            {EDITABLE_KEYS.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <label>
          API key
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="stored in workspace settings"
            autoComplete="off"
          />
        </label>
        <label>
          Base URL
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="optional override"
          />
        </label>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </form>

      <p className="muted">
        Workspace settings are preferred over environment variables when a
        research run starts. Leave fields blank to fall back to env / compose
        defaults.
      </p>

      <h2>Provider catalogs</h2>
      {providers && (
        <>
          <h3>LLM providers</h3>
          <div className="provider-list" aria-label="llm providers">
            {providers.llm_providers.length === 0 && (
              <span className="muted">None registered</span>
            )}
            {providers.llm_providers.map((p) => (
              <code key={p}>{p}</code>
            ))}
          </div>

          <h3>Search engines</h3>
          <div className="provider-list" aria-label="search engines">
            {providers.search_engines.length === 0 && (
              <span className="muted">None registered</span>
            )}
            {providers.search_engines.map((p) => (
              <code key={p}>{p}</code>
            ))}
          </div>

          <h3>Search strategies</h3>
          <div className="provider-list" aria-label="search strategies">
            {providers.search_strategies.length === 0 && (
              <span className="muted">None registered</span>
            )}
            {providers.search_strategies.map((p) => (
              <code key={p}>{p}</code>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
