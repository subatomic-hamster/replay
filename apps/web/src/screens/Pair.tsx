// H4 placeholder (P1). Shows the pairing code from POST /sessions; the WebSocket push
// from the phone companion is not wired up yet.
// ponytail: no WS client until services/api actually serves /sessions/{sid}.
import { useCallback } from "react";
import { api } from "../api/client";
import { useDpad } from "../platform/keys";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";

export function Pair() {
  const { data, error, reload } = useAsync(() => api.createSession(), []);
  useDpad(
    useCallback((a: string) => {
      if (a === "back") navigate("/tv");
    }, []),
  );

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="screen pair">
      <h1>Pair your phone</h1>
      <p>On your phone, open the Replay page and enter this code:</p>
      <p className="pair-code" data-testid="pair-code">
        {data?.code ?? "…"}
      </p>
      <p className="hint">Escape returns to the library</p>
    </div>
  );
}
