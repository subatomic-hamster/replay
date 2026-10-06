import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  useEffect(() => {
    let live = true;
    setError(null);
    run().then(
      (v) => live && setData(v),
      (e: Error) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [run, nonce]);

  return { data, error, reload: () => setNonce((n) => n + 1) };
}

/** E-22: every screen that fetches renders this instead of a white page. */
export function ApiErrorBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="api-error" data-testid="api-error" role="alert">
      <p>Could not reach the Replay API.</p>
      <p className="dim">{error.message}</p>
      <button type="button" onClick={onRetry} autoFocus>
        Retry
      </button>
    </div>
  );
}

export { fmtDate, fmtDuration } from "../../../packages/tv-core/src/display";
