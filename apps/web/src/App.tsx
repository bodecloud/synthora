import { useEffect, useState } from "react";
import {
  clearToken,
  getToken,
  loadStoredToken,
} from "./api";
import { Chat } from "./components/Chat";
import { Documents } from "./components/Documents";
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
  | { name: "documents" }
  | { name: "run"; runId: string };

const CHAT_SESSION_KEY = "synthora_chat_session";

export function App() {
  const [view, setView] = useState<View>({ name: "new" });
  const [authed, setAuthed] = useState(() => Boolean(loadStoredToken()));
  const [chatSessionId, setChatSessionId] = useState(() => {
    if (typeof sessionStorage === "undefined") return "";
    return sessionStorage.getItem(CHAT_SESSION_KEY) || "";
  });

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, [view]);

  function persistChatSession(id: string) {
    setChatSessionId(id);
    if (typeof sessionStorage !== "undefined") {
      if (id) sessionStorage.setItem(CHAT_SESSION_KEY, id);
      else sessionStorage.removeItem(CHAT_SESSION_KEY);
    }
  }

  function signOut() {
    clearToken();
    setAuthed(false);
    persistChatSession("");
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
            className={view.name === "documents" ? "active" : ""}
            onClick={() => setView({ name: "documents" })}
          >
            Documents
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
          <Chat
            sessionId={chatSessionId}
            onSessionId={persistChatSession}
            onStarted={(runId) => setView({ name: "run", runId })}
          />
        )}
        {view.name === "news" && <News />}
        {view.name === "documents" && <Documents />}
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
