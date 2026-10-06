// H4 (S-31) — pairing screen. Shows the 4-digit code from POST /sessions and listens on
// the session WebSocket; a `{type:"query"}` push from the phone opens Highlights for the
// game we came from.
import { useCallback, useState } from "react";
import { View } from "react-native";
import { api } from "../api";
import { useDpad } from "../input";
import { navigate } from "../nav";
import { storeSession, storedSession, useSessionMessages } from "../session";
import { color, px } from "../theme";
import { ApiErrorBanner, Hint, T, styles as ui, useAsync } from "../ui";

export function Pair({ gameId }: { gameId?: string }) {
  const [session, setSession] = useState(storedSession);
  const { error, reload } = useAsync(async () => {
    // Reuse the code already shown instead of minting a second session.
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
          navigate({ name: "highlights", gameId, q: msg.text });
        }
      },
      [gameId],
    ),
  );

  useDpad(
    useCallback(
      (a) => {
        if (a === "back") navigate(gameId ? { name: "watch", gameId } : { name: "library" });
      },
      [gameId],
    ),
  );

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <View style={ui.screen}>
      <T style={ui.h1}>Pair your phone</T>
      <T>Open /companion on your phone and enter this code:</T>
      <T
        testID="pair-code"
        style={{ fontSize: px(160), fontWeight: "800", letterSpacing: px(24), color: color.accent, marginVertical: px(32) }}
      >
        {session?.code ?? "…"}
      </T>
      <Hint>
        {gameId
          ? "Type or speak a query on the phone — the TV jumps to the results."
          : "Open a game first so phone queries have something to search."}
      </Hint>
      <Hint>Back returns</Hint>
    </View>
  );
}
