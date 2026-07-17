import { useEffect, useRef } from "react";
import { RunEvent } from "../api";

export function EventFeed({ events }: { events: RunEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="event-feed" role="log" aria-label="run events">
      {events.length === 0 && <div className="event-line">waiting…</div>}
      {events.map((e, i) => (
        <div key={i} className="event-line">
          <span className="event-type">[{e.type}]</span>{" "}
          {e.node ? `${e.node}: ` : ""}
          {e.message}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
