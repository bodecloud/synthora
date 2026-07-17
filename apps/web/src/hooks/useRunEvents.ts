import { useEffect, useRef, useState } from "react";
import { eventsSocketUrl, RunEvent, TERMINAL_STATUSES } from "../api";

/** Live event stream over WebSocket with automatic terminal detection. */
export function useRunEvents(runId: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [finished, setFinished] = useState(false);
  /** Bumps when run status changes (including awaiting_input) so views re-fetch. */
  const [statusTick, setStatusTick] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setEvents([]);
    setFinished(false);
    setStatusTick(0);
    const socket = new WebSocket(eventsSocketUrl(runId));
    socketRef.current = socket;
    socket.onmessage = (msg) => {
      const event: RunEvent = JSON.parse(msg.data);
      setEvents((prev) => [...prev, event]);
      if (event.type === "done" || event.type === "error") {
        setFinished(true);
      }
      const status = (event.payload?.status as string) || "";
      if (event.type === "status") {
        setStatusTick((n) => n + 1);
        if (TERMINAL_STATUSES.includes(status)) {
          setFinished(true);
        }
      }
      if (event.type === "interrupt") {
        setStatusTick((n) => n + 1);
      }
    };
    socket.onclose = () => setFinished(true);
    return () => socket.close();
  }, [runId]);

  return { events, finished, statusTick };
}
