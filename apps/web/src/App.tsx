import { useEffect, useState } from "react";
import {
  clearToken,
  getToken,
  loadStoredToken,
} from "./api";
import { Chat } from "./components/Chat";
import { History } from "./components/History";
import { Login } from "./components/Login";
import { News } from "./components/News";
import { NewResearch } from "./components/NewResearch";
import { RunView } from "./components/RunView";
import { Settings } from "./components/Settings";

type View =
  | { name: "new" }
  | { name: "history" }
  | { name: "settings" }
  | { name: "login" }
  | { name: "news" }
  | { name: "chat" }
  | { name: "run"; runId: string };

export function App() {
  const [view, setView] = useState<View>({ name: "new" });
  const [authed, setAuthed] = useState(() => Boolean(loadStoredToken()));

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, [view]);

  function signOut() {
    clearToken();
    setAuthed(false);
    setView({ name: "login" });
  }

  return (
    <>
      <header className="masthead">
        <h1>
          Syn<span>thora</span>
        </h1>
        <nav>
          <button
            className={view.name === "new" ? "active" : ""}
            onClick={() => setView({ name: "new" })}
          >
            New research
          </button>
          <button
            className={view.name === "chat" ? "active" : ""}
            onClick={() => setView({ name: "chat" })}
          >
            Chat
          </button>
          <button
            className={view.name === "news" ? "active" : ""}
            onClick={() => setView({ name: "news" })}
          >
            News
          </button>
          <button
            className={view.name === "history" ? "active" : ""}
            onClick={() => setView({ name: "history" })}
          >
            History
          </button>
          <button
            className={view.name === "settings" ? "active" : ""}
            onClick={() => setView({ name: "settings" })}
          >
            Settings
          </button>
          {authed ? (
            <button className="ghost" onClick={signOut}>
              Sign out
            </button>
          ) : (
            <button
              className={view.name === "login" ? "active" : ""}
              onClick={() => setView({ name: "login" })}
            >
              Login
            </button>
          )}
        </nav>
      </header>
      <main>
        {view.name === "new" && (
          <NewResearch onStarted={(runId) => setView({ name: "run", runId })} />
        )}
        {view.name === "chat" && (
          <Chat onStarted={(runId) => setView({ name: "run", runId })} />
        )}
        {view.name === "news" && <News />}
        {view.name === "history" && (
          <History onOpen={(runId) => setView({ name: "run", runId })} />
        )}
        {view.name === "settings" && <Settings />}
        {view.name === "login" && (
          <Login
            onAuthed={() => {
              setAuthed(true);
              setView({ name: "new" });
            }}
          />
        )}
        {view.name === "run" && (
          <RunView
            runId={view.runId}
            onDeleted={() => setView({ name: "history" })}
            onFollowup={(runId) => setView({ name: "run", runId })}
          />
        )}
      </main>
    </>
  );
}
