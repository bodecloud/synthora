import { useEffect, useRef, useState } from "react";
import { api, eventsSocketUrl, RunEvent, TERMINAL_STATUSES } from "../api";

const MAX_BACKOFF_MS = 15000;

/** Live event stream over WebSocket with reconnect + REST gap-fill. */
export function useRunEvents(runId: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [finished, setFinished] = useState(false);
  /** Bumps when run status changes (including awaiting_input) so views re-fetch. */
  const [statusTick, setStatusTick] = useState(0);
  const finishedRef = useRef(false);
  const eventsRef = useRef<RunEvent[]>([]);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    finishedRef.current = false;
    eventsRef.current = [];
    setEvents([]);
    setFinished(false);
    setStatusTick(0);

    function mergeEvents(incoming: RunEvent[]) {
      if (!incoming.length) return;
      const byKey = new Map<string, RunEvent>();
      for (const e of eventsRef.current) {
        byKey.set(`${e.timestamp}|${e.type}|${e.message}`, e);
      }
      for (const e of incoming) {
        byKey.set(`${e.timestamp}|${e.type}|${e.message}`, e);
      }
      const merged = Array.from(byKey.values()).sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp),
      );
      eventsRef.current = merged;
      setEvents(merged);
    }

    function handleEvent(event: RunEvent) {
      mergeEvents([event]);
      if (event.type === "done" || event.type === "error") {
        finishedRef.current = true;
        setFinished(true);
      }
      const status = (event.payload?.status as string) || "";
      if (event.type === "status") {
        setStatusTick((n) => n + 1);
        if (TERMINAL_STATUSES.includes(status)) {
          finishedRef.current = true;
          setFinished(true);
        }
      }
      if (event.type === "interrupt") {
        setStatusTick((n) => n + 1);
      }
    }

    async function fillGaps() {
      try {
        const remote = await api.getEvents(runId);
        if (cancelled) return;
        mergeEvents(remote);
        const lastStatus = [...remote]
          .reverse()
          .find((e) => e.type === "status" || e.type === "done" || e.type === "error");
        const status = (lastStatus?.payload?.status as string) || "";
        if (
          lastStatus?.type === "done" ||
          lastStatus?.type === "error" ||
          TERMINAL_STATUSES.includes(status)
        ) {
          finishedRef.current = true;
          setFinished(true);
        }
      } catch {
        /* REST gap-fill is best-effort while WS is primary */
      }
    }

    function connect() {
      if (cancelled || finishedRef.current) return;
      socket = new WebSocket(eventsSocketUrl(runId));
      socket.onopen = () => {
        attempt = 0;
        void fillGaps();
      };
      socket.onmessage = (msg) => {
        const event: RunEvent = JSON.parse(msg.data);
        handleEvent(event);
      };
      socket.onclose = () => {
        socket = null;
        if (cancelled || finishedRef.current) return;
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), MAX_BACKOFF_MS);
        reconnectTimer = setTimeout(() => {
          void fillGaps().finally(connect);
        }, delay);
      };
      socket.onerror = () => {
        socket?.close();
      };
    }

    void fillGaps().finally(connect);

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [runId]);

  return { events, finished, statusTick };
}
