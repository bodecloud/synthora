import { expect, test } from "@playwright/test";

/**
 * Playwright smoke against API mocks (plan U7).
 * Does not require a live backend — stubs fetch + WebSocket.
 */

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class MockWebSocket {
      static OPEN = 1;
      readyState = MockWebSocket.OPEN;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onclose: ((ev: CloseEvent) => void) | null = null;
      constructor(_url: string) {
        queueMicrotask(() => this.onopen?.(new Event("open")));
        queueMicrotask(() => {
          this.onmessage?.(
            new MessageEvent("message", {
              data: JSON.stringify({
                type: "status",
                message: "queued",
                payload: { status: "queued" },
              }),
            }),
          );
        });
      }
      send() {}
      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
    }
    // @ts-expect-error mock
    window.WebSocket = MockWebSocket;

    const json = (data: unknown, status = 200) =>
      Promise.resolve(
        new Response(JSON.stringify(data), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/api/v1/pipelines")) {
        return json({
          pipelines: [
            {
              id: "fast_research",
              name: "Fast",
              description: "Quick pass",
              tags: ["fast"],
            },
          ],
        });
      }
      if (url.includes("/api/v1/providers")) {
        return json({
          llm_providers: ["openai", "ollama"],
          search_engines: ["searxng", "tavily"],
          search_strategies: ["source_based"],
        });
      }
      if (url.includes("/api/v1/sessions") && method === "GET") {
        return json({ sessions: [] });
      }
      if (url.match(/\/api\/v1\/research\/[^/?]+\/events/) && method === "GET") {
        return json({ events: [] });
      }
      if (url.match(/\/api\/v1\/research\/[^/?]+\/discourse/)) {
        return json({ turns: [] });
      }
      if (
        url.match(/\/api\/v1\/research\/[^/?]+$/) &&
        method === "GET" &&
        !url.endsWith("/research")
      ) {
        return json({
          id: "run-e2e",
          question: "What is QEC?",
          pipeline_id: "fast_research",
          session_id: null,
          status: "queued",
          created_at: new Date().toISOString(),
          finished_at: null,
          brief: null,
          error: null,
        });
      }
      if (url.includes("/api/v1/research") && method === "POST") {
        return json(
          { run_id: "run-e2e", status: "queued", session_id: null },
          202,
        );
      }
      if (url.includes("/api/v1/research") && method === "GET") {
        return json({ runs: [] });
      }
      if (url.includes("/api/v1/settings")) {
        return json({ settings: [] });
      }
      return json({ detail: "unmocked " + url }, 404);
    };
  });
});

test("new research form lists pipelines and starts a run", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /ask a research question/i }),
  ).toBeVisible({ timeout: 15_000 });
  await page.getByPlaceholder(/understand deeply/i).fill("What is QEC?");
  await page.getByRole("button", { name: /start research/i }).click();
  await expect(page.getByText("What is QEC?").first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText(/queued|running|status/i).first()).toBeVisible();
});
