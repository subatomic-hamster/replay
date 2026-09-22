// H4 (S-31) — pairing screen. Shows the 4-digit code from POST /sessions and listens on
// the session WebSocket; a `{type:"query"}` push from the phone jumps straight to the
// Highlights screen for the game we were paired from (`?game=`, set by the `p` key).
import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useDpad } from "../platform/keys";
import { navigate, useLocation } from "../router";
import { storeSession, storedSession, useSessionMessages } from "../session";
import { ApiErrorBanner, useAsync } from "../ui";

export function Pair() {
  const { params } = useLocation();
  const gameId = params.get("game");
  const [session, setSession] = useState(storedSession);
  const { error, reload } = useAsync(async () => {
    // Reuse the code already on screen elsewhere instead of minting a second session.
    const existing = storedSession();
    if (existing) return existing;
    const created = await api.createSession();
    storeSession(created);
    setSession(created);
    return created;
  }, []);

  useSessionMessages(
    session?.id,
    useCallback(
      (msg) => {
        if (msg.type === "query" && msg.text && gameId) {
          navigate(`/tv/${gameId}/highlights?q=${encodeURIComponent(msg.text)}`);
        }
      },
      [gameId],
    ),
  );

  useDpad(
    useCallback(
      (a: string) => {
        if (a === "back") navigate(gameId ? `/tv/${gameId}/highlights` : "/tv");
      },
      [gameId],
    ),
  );

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="screen pair">
      <h1>Pair your phone</h1>
      <p>Open /companion on your phone and enter this code:</p>
      <p className="pair-code" data-testid="pair-code">
        {session?.code ?? "…"}
      </p>
      <p className="hint">
        {gameId
          ? "Type or speak a query on the phone — the TV jumps to the results."
          : "Open a game first so phone queries have something to search."}
      </p>
      <p className="hint">
        <b>Escape</b> goes back
      </p>
    </div>
  );
}
