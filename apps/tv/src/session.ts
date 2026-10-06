// H4 phone companion — the TV side of the pairing session. One app process per TV, so
// the session lives in a module variable (no sessionStorage on Fire OS); Pair, Watch and
// Highlights share it.
import { useCallback, useEffect, useRef } from "react";
import type { Session } from "../../../packages/tv-core/src/types";
import { wsUrl } from "./api";

let session: Session | null = null;

export const storedSession = () => session;
export const storeSession = (s: Session) => {
  session = s;
};

/** Phone → TV: `query` (S-31), `seek` (play a search hit), `clip` (a tap cut a clip).
 *  TV → phone: `now` (what is on screen, so a tap knows its game and media time). */
export interface SessionMessage {
  type: string;
  text?: string;
  game_id?: string;
  title?: string;
  t?: number;
  label?: string;
}

/** Subscribe to the paired phone's pushes (S-31); reconnects only when the id changes.
 *  Returns a `send` for the other direction (dropped while the socket is not open). */
export function useSessionMessages(
  sessionId: string | null | undefined,
  onMessage: (msg: SessionMessage) => void,
): (msg: SessionMessage) => void {
  const handler = useRef(onMessage);
  const socket = useRef<WebSocket | null>(null);
  useEffect(() => {
    handler.current = onMessage;
  });

  useEffect(() => {
    if (!sessionId) return;
    const ws = new WebSocket(wsUrl(sessionId));
    socket.current = ws;
    ws.onmessage = (e) => {
      try {
        handler.current(JSON.parse(String(e.data)) as SessionMessage);
      } catch {
        /* not ours */
      }
    };
    return () => {
      socket.current = null;
      ws.close();
    };
  }, [sessionId]);

  return useCallback((msg: SessionMessage) => {
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);
}
