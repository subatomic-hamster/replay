// H4 phone companion — the TV side of the pairing session.
//
// The session id lives in sessionStorage so the Pair screen, Watch and Highlights all
// talk to the same socket after a navigation (a plain module variable dies on the
// full page loads the router does not do, but sessionStorage is free and survives both).
// ponytail: one socket per screen, no shared connection manager — a TV shows one screen.
import { useCallback, useEffect, useRef } from "react";
import { sessionWsUrl } from "./api/client";
import type { Session } from "./api/types";

const KEY = "replay.session";

export function storedSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function storeSession(session: Session): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    /* private mode: the current screen still works, a reload just re-pairs */
  }
}

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

/**
 * Subscribe to the paired phone's pushes (S-31). Reconnects only when the session id
 * changes; `onMessage` is read through a ref so a re-render does not drop the socket.
 * Returns a `send` for the other direction (dropped while the socket is not open).
 */
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
    const ws = new WebSocket(sessionWsUrl(sessionId));
    socket.current = ws;
    ws.onmessage = (e) => {
      try {
        handler.current(JSON.parse(e.data as string) as SessionMessage);
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
