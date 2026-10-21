import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { API } from "./api/client";

const TYPES = ["run_status", "steps", "step", "log", "chat_message", "run_finished"];

/** Subscribe to a run's SSE stream; every event refreshes the run and the run list. */
export function useRunEvents(runId: string | null, onEvent?: (ev: any) => void) {
  const qc = useQueryClient();
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`${API}/runs/${runId}/events`);
    const handle = (e: MessageEvent) => {
      const ev = JSON.parse(e.data);
      cb.current?.(ev);
      qc.invalidateQueries({ queryKey: ["run", runId] });
      if (ev.type === "run_status" || ev.type === "run_finished") qc.invalidateQueries({ queryKey: ["runs"] });
      if (ev.type === "run_finished") es.close();
    };
    TYPES.forEach((t) => es.addEventListener(t, handle));
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId, qc]);
}
