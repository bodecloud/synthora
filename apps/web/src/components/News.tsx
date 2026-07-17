import { useEffect, useState } from "react";
import { api, NewsItem, NewsSubscription } from "../api";

export function News() {
  const [subs, setSubs] = useState<NewsSubscription[]>([]);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [query, setQuery] = useState("");
  const [cadence, setCadence] = useState("daily");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const [s, i] = await Promise.all([
      api.listNewsSubscriptions(),
      api.listNewsItems(),
    ]);
    setSubs(s);
    setItems(i);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, []);

  async function createSub() {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createNewsSubscription(query.trim(), cadence);
      setQuery("");
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function fetchSub(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.fetchNewsSubscription(id);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeSub(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteNewsSubscription(id);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>News subscriptions</h2>
      {error && <p className="error-text">{error}</p>}
      <div className="steer-row">
        <input
          type="text"
          placeholder="Query (e.g. AI regulation news)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="news query"
        />
        <select
          value={cadence}
          onChange={(e) => setCadence(e.target.value)}
          aria-label="cadence"
        >
          <option value="hourly">hourly</option>
          <option value="daily">daily</option>
          <option value="weekly">weekly</option>
        </select>
        <button
          className="primary"
          type="button"
          disabled={busy || !query.trim()}
          onClick={createSub}
        >
          Subscribe
        </button>
      </div>

      <ul className="history-list">
        {subs.map((s) => (
          <li key={s.id}>
            <div>
              <strong>{s.query}</strong>
              <span className="muted"> · {s.cadence}</span>
            </div>
            <div className="action-row">
              <button
                className="ghost"
                type="button"
                disabled={busy}
                onClick={() => fetchSub(s.id)}
              >
                Fetch now
              </button>
              <button
                className="ghost danger"
                type="button"
                disabled={busy}
                onClick={() => removeSub(s.id)}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      <h3>Items</h3>
      {items.length === 0 && <p className="muted">No news items yet.</p>}
      <ul className="history-list">
        {items.map((item) => (
          <li key={item.id}>
            <a href={item.url} target="_blank" rel="noreferrer">
              {item.title || item.url}
            </a>
            {item.summary && <p className="muted">{item.summary}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
