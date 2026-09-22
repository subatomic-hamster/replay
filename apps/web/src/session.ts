// H4 phone companion — the TV side of the pairing session.
//
// The session id lives in sessionStorage so the Pair screen, Watch and Highlights all
// talk to the same socket after a navigation (a plain module variable dies on the
// full page loads the router does not do, but sessionStorage is free and survives both).
// ponytail: one socket per screen, no shared connection manager — a TV shows one screen.
import { useEffect, useRef } from "react";
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

export interface SessionMessage {
  type: string;
  text?: string;
}

/**
 * Subscribe to the paired phone's pushes (S-31). Reconnects only when the session id
 * changes; `onMessage` is read through a ref so a re-render does not drop the socket.
 */
export function useSessionMessages(
  sessionId: string | null | undefined,
  onMessage: (msg: SessionMessage) => void,
) {
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!sessionId) return;
    const ws = new WebSocket(sessionWsUrl(sessionId));
    ws.onmessage = (e) => {
      try {
        handler.current(JSON.parse(e.data as string) as SessionMessage);
      } catch {
        /* not ours */
      }
    };
    return () => ws.close();
  }, [sessionId]);
}
