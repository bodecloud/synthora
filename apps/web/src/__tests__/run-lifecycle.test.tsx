// U7: component tests for the run lifecycle against mocked API + WebSocket.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { History } from "../components/History";
import { KnowledgeMapView } from "../components/KnowledgeMapView";
import { NewResearch } from "../components/NewResearch";
import { RunView } from "../components/RunView";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onmessage: ((msg: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  send() {}
  close() {}
  emit(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

const fetchMock = vi.fn();

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response);
}

const PIPELINES = {
  pipelines: [
    { id: "fast_research", name: "Fast research", description: "quick", tags: [] },
    { id: "deep_research", name: "Deep research", description: "deep", tags: [] },
  ],
};

const PROVIDERS = {
  llm_providers: ["openai", "anthropic"],
  search_engines: ["searxng", "tavily"],
  search_strategies: ["source_based", "planning"],
};

const SESSIONS = {
  sessions: [
    {
      id: "sess-1",
      title: "My session",
      tags: [],
      workspace_id: "default",
      created_at: new Date().toISOString(),
    },
  ],
};

describe("NewResearch", () => {
  it("lists pipelines and starts a run", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/v1/pipelines") return jsonResponse(PIPELINES);
      if (url === "/api/v1/providers") return jsonResponse(PROVIDERS);
      if (url === "/api/v1/sessions") return jsonResponse(SESSIONS);
      if (url === "/api/v1/research" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.question).toBe("What is X?");
        expect(body.pipeline_id).toBe("fast_research");
        expect(body.config).toBeTruthy();
        expect(body.config.allow_clarification).toBe(false);
        return jsonResponse({ run_id: "r1", status: "queued", session_id: null });
      }
      throw new Error(`unexpected ${url}`);
    });

    const onStarted = vi.fn();
    render(<NewResearch onStarted={onStarted} />);
    await screen.findByText("Fast research");

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("research question"),
      "What is X?",
    );
    await user.click(screen.getByText("Fast research"));
    await user.click(screen.getByRole("button", { name: /start research/i }));

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("r1"));
  });

  it("disables start until a question is typed", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/v1/pipelines") return jsonResponse(PIPELINES);
      if (url === "/api/v1/providers") return jsonResponse(PROVIDERS);
      if (url === "/api/v1/sessions") return jsonResponse(SESSIONS);
      throw new Error(`unexpected ${url}`);
    });
    render(<NewResearch onStarted={() => {}} />);
    const button = await screen.findByRole("button", {
      name: /start research/i,
    });
    expect(button).toBeDisabled();
  });
});

describe("RunView lifecycle", () => {
  it("streams events and shows the report when completed", async () => {
    let status = "running";
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/v1/research/r1")
        return jsonResponse({
          id: "r1",
          question: "Deep question?",
          brief: "the brief",
          pipeline_id: "deep_research",
          session_id: null,
          status,
          error: null,
          config: {},
          created_at: new Date().toISOString(),
          started_at: null,
          finished_at: null,
        });
      if (url === "/api/v1/research/r1/discourse")
        return jsonResponse({ turns: [] });
      if (url === "/api/v1/research/r1/report")
        return jsonResponse({
          report_markdown: "# Final Report",
          citations: [
            {
              id: "c1",
              url: "https://example.com",
              title: "Example",
              snippet: "",
              confidence: 1,
              index: 1,
              verified: true,
            },
          ],
          status: "completed",
        });
      if (url === "/api/v1/research/r1/knowledge-map")
        return jsonResponse({ nodes: [], edges: [] });
      throw new Error(`unexpected ${url}`);
    });

    render(<RunView runId="r1" />);
    await screen.findByText("Deep question?");
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export markdown/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export html/i })).toBeInTheDocument();

    const socket = MockWebSocket.instances[0];
    socket.emit({
      run_id: "r1",
      type: "node_started",
      message: "Writing research brief",
      node: "brief",
      payload: {},
      timestamp: new Date().toISOString(),
    });
    await screen.findByText(/Writing research brief/);

    status = "completed";
    socket.emit({
      run_id: "r1",
      type: "done",
      message: "completed",
      node: null,
      payload: { status: "completed" },
      timestamp: new Date().toISOString(),
    });

    await screen.findByText("Final Report");
    await screen.findByText("Example");
    // status badge shows terminal state (also appears in the event feed)
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("offers cancel and steer while running", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/v1/research/r2")
        return jsonResponse({
          id: "r2",
          question: "q",
          brief: null,
          pipeline_id: "fast_research",
          session_id: null,
          status: "running",
          error: null,
          config: {},
          created_at: new Date().toISOString(),
          started_at: null,
          finished_at: null,
        });
      if (url === "/api/v1/research/r2/discourse")
        return jsonResponse({ turns: [] });
      if (url === "/api/v1/research/r2/steer" && init?.method === "POST") {
        expect(JSON.parse(String(init.body)).message).toBe("focus on cost");
        return jsonResponse({ steered: true });
      }
      throw new Error(`unexpected ${url}`);
    });

    render(<RunView runId="r2" />);
    await screen.findByText("Cancel run");

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("steering message"),
      "focus on cost",
    );
    await user.click(screen.getByRole("button", { name: "Steer" }));
  });

  it("shows clarification form and resumes when awaiting_input", async () => {
    let status = "awaiting_input";
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/v1/research/r3")
        return jsonResponse({
          id: "r3",
          question: "Clarify me?",
          brief: null,
          pipeline_id: "deep_research",
          session_id: "sess-1",
          status,
          error: null,
          config: { allow_clarification: true },
          created_at: new Date().toISOString(),
          started_at: null,
          finished_at: null,
        });
      if (url === "/api/v1/research/r3/discourse")
        return jsonResponse({
          turns: [
            {
              id: "t1",
              run_id: "r3",
              speaker: "moderator",
              role: "moderator",
              utterance: "Which region matters most?",
              intent: "question",
              citations: [],
              created_at: new Date().toISOString(),
            },
          ],
        });
      if (url === "/api/v1/research/r3/resume" && init?.method === "POST") {
        expect(JSON.parse(String(init.body)).answer).toBe("North America");
        status = "queued";
        return jsonResponse({ run_id: "r3", status: "queued", resumed: true });
      }
      throw new Error(`unexpected ${url}`);
    });

    render(<RunView runId="r3" />);
    await screen.findByText("Clarification needed");
    expect(screen.getByText("awaiting_input")).toBeInTheDocument();
    expect(screen.getByText("Which region matters most?")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /export markdown/i }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("clarification answer"),
      "North America",
    );
    await user.click(screen.getByRole("button", { name: /resume/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/research/r3/resume",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});

describe("History", () => {
  it("renders runs and opens one on click", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/v1/research" || url.startsWith("/api/v1/research?")) {
        return jsonResponse({
          runs: [
            {
              id: "r9",
              question: "old research",
              pipeline_id: "fast_research",
              session_id: "sess-abc",
              status: "completed",
              created_at: new Date().toISOString(),
              finished_at: new Date().toISOString(),
            },
          ],
        });
      }
      if (url === "/api/v1/sessions") {
        return jsonResponse({
          sessions: [
            {
              id: "sess-abc",
              title: "Archive session",
              tags: [],
              workspace_id: "default",
              created_at: new Date().toISOString(),
            },
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    const onOpen = vi.fn();
    render(<History onOpen={onOpen} />);
    const row = await screen.findByText("old research");
    expect(screen.getAllByText("Archive session").length).toBeGreaterThan(0);
    const user = userEvent.setup();
    await user.click(row);
    expect(onOpen).toHaveBeenCalledWith("r9");
  });
});

describe("KnowledgeMapView", () => {
  it("renders the node hierarchy", () => {
    render(
      <KnowledgeMapView
        nodes={[
          { id: "a", name: "Root", summary: "", parent_id: null, infos: [] },
          {
            id: "b",
            name: "Child concept",
            summary: "",
            parent_id: "a",
            infos: [
              {
                id: "c",
                url: "u",
                title: "t",
                snippet: "",
                confidence: 1,
                index: 1,
                verified: false,
              },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText("Root")).toBeInTheDocument();
    expect(screen.getByText("Child concept")).toBeInTheDocument();
    expect(screen.getByText("1 sources")).toBeInTheDocument();
  });
});
