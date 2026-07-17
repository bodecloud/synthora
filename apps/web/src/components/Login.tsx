import { FormEvent, useState } from "react";
import { api, setToken } from "../api";

export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result =
        mode === "login"
          ? await api.login(username.trim(), password)
          : await api.register(username.trim(), password);
      setToken(result.token);
      onAuthed();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>{mode === "login" ? "Sign in" : "Create account"}</h2>
      <p className="muted">
        Session auth stores a Bearer token in localStorage for API calls.
      </p>
      <form className="login-form" onSubmit={submit}>
        <label>
          Username
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            aria-label="username"
            required
            minLength={3}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label="password"
            required
            minLength={mode === "register" ? 8 : 1}
          />
        </label>
        {error && <p className="error-text">{error}</p>}
        <div className="action-row">
          <button className="primary" type="submit" disabled={busy}>
            {busy
              ? "Working…"
              : mode === "login"
                ? "Sign in"
                : "Register"}
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() =>
              setMode(mode === "login" ? "register" : "login")
            }
          >
            {mode === "login" ? "Need an account?" : "Have an account?"}
          </button>
        </div>
      </form>
    </section>
  );
}
