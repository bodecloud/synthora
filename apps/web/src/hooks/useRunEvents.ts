import { useEffect, useRef, useState } from "react";
import { eventsSocketUrl, RunEvent, TERMINAL_STATUSES } from "../api";

/** Live event stream over WebSocket with automatic terminal detection. */
export function useRunEvents(runId: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [finished, setFinished] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setEvents([]);
    setFinished(false);
    const socket = new WebSocket(eventsSocketUrl(runId));
    socketRef.current = socket;
    socket.onmessage = (msg) => {
      const event: RunEvent = JSON.parse(msg.data);
      setEvents((prev) => [...prev, event]);
      if (event.type === "done" || event.type === "error") {
        setFinished(true);
      }
      const status = (event.payload?.status as string) || "";
      if (event.type === "status" && TERMINAL_STATUSES.includes(status)) {
        setFinished(true);
      }
    };
    socket.onclose = () => setFinished(true);
    return () => socket.close();
  }, [runId]);

  return { events, finished };
}
