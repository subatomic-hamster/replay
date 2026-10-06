// H4 phone companion — the TV side of the pairing session. One app process per TV, so
// the session lives in a module variable (no sessionStorage on Fire OS); Pair, Watch and
// Highlights share it.
import { useEffect, useRef } from "react";
import type { Session } from "../../../packages/tv-core/src/types";
import { wsUrl } from "./api";

let session: Session | null = null;

export const storedSession = () => session;
export const storeSession = (s: Session) => {
  session = s;
};

export interface SessionMessage {
  type: string;
  text?: string;
}

/** Subscribe to the paired phone's pushes (S-31); reconnects only when the id changes. */
export function useSessionMessages(
  sessionId: string | null | undefined,
  onMessage: (msg: SessionMessage) => void,
) {
  const handler = useRef(onMessage);
  useEffect(() => {
    handler.current = onMessage;
  });

  useEffect(() => {
    if (!sessionId) return;
    const ws = new WebSocket(wsUrl(sessionId));
    ws.onmessage = (e) => {
      try {
        handler.current(JSON.parse(String(e.data)) as SessionMessage);
      } catch {
        /* not ours */
      }
    };
    return () => ws.close();
  }, [sessionId]);
}
