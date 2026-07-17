import { useCallback, useEffect, useState } from "react";
import { api, DocumentSummary } from "../api";

export function Documents() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .listDocuments()
      .then(setDocs)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function upload() {
    if (!title.trim() || !content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createDocument(title.trim(), content.trim());
      setTitle("");
      setContent("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.searchDocuments(query.trim());
      setHits(result.results || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this document?")) return;
    try {
      await api.deleteDocument(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <section className="panel">
      <h2>Document library</h2>
      <p className="muted">
        Upload texts for the <code>collection</code> search engine (workspace
        RAG).
      </p>
      {error && <p className="error-text">{error}</p>}

      <div className="form-grid">
        <label>
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="document title"
          />
        </label>
        <label>
          Content
          <textarea
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            aria-label="document content"
          />
        </label>
        <button
          className="primary"
          type="button"
          disabled={busy || !title.trim() || !content.trim()}
          onClick={upload}
        >
          {busy ? "Saving…" : "Upload document"}
        </button>
      </div>

      <div className="steer-row" style={{ marginTop: "1rem" }}>
        <input
          type="text"
          placeholder="Search library…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="document search"
        />
        <button
          className="primary"
          type="button"
          disabled={busy || !query.trim()}
          onClick={search}
        >
          Search
        </button>
      </div>
      {hits.length > 0 && (
        <ul>
          {hits.map((h, i) => (
            <li key={i}>
              <strong>{String(h.title || h.url || "hit")}</strong>
              <p className="muted">{String(h.snippet || h.content || "")}</p>
            </li>
          ))}
        </ul>
      )}

      <h3 style={{ marginTop: "1.5rem" }}>Documents ({docs.length})</h3>
      {docs.length === 0 ? (
        <p>No documents yet.</p>
      ) : (
        <ul>
          {docs.map((d) => (
            <li key={d.id}>
              {d.title}{" "}
              <button
                type="button"
                className="ghost danger"
                onClick={() => remove(d.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
