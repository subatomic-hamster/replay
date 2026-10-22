// D-87: the cloud API runs on Lambda with an account concurrency of 10, and a Watch open
// alone is several requests. A throttled request (429; or a 503 that says so with
// Retry-After or a throttle body) never ran, so the clients try it again a few times with
// jittered backoff, within about 4 s, before the screen shows its usual error. Only for
// requests that are safe to repeat: reads, and writes the API makes idempotent.

export const RETRY_CAP_MS = 4000;
export const RETRY_TRIES = 4;
const BASE_MS = 300;
const THROTTLE_BODY = /rate exceeded|too many requests|throttl/i;

/** Methods that are safe to send twice; a POST is only when the caller says so. */
export const idempotent = (method?: string) =>
  !method || /^(GET|HEAD|OPTIONS|PUT|PATCH|DELETE)$/i.test(method);

export interface RetryDeps {
  fetch?: (url: string, init?: RequestInit) => Promise<Response>;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  now?: () => number;
}

/** How long to wait before trying `res` again, or null when it is not a throttle. */
export async function throttleWait(
  res: Response,
  attempt: number,
  random: () => number = Math.random,
  now: () => number = Date.now,
): Promise<number | null> {
  if (res.status !== 429 && res.status !== 503) return null;
  const after = res.headers.get("retry-after");
  if (after) {
    // seconds, or an HTTP date; a little jitter so throttled clients spread out
    const s = Number(after);
    const ms = Number.isFinite(s) ? s * 1000 : Date.parse(after) - now();
    if (Number.isFinite(ms)) return Math.max(0, ms) + random() * 100;
  }
  // full jitter on an exponential step, never zero
  const backoff = 100 + random() * BASE_MS * 2 ** attempt;
  if (res.status === 429) return backoff;
  // a 503 is our API's own "not available" unless the body says throttle
  const body = await res
    .clone()
    .text()
    .catch(() => "");
  return THROTTLE_BODY.test(body) ? backoff : null;
}

/** At most this many API requests in flight from this app; the rest queue in order
 *  (the account's Lambda concurrency is 10 for every viewer and phone together). */
export const MAX_IN_FLIGHT = 4;
let inFlight = 0;
const waiting: (() => void)[] = [];

/** Wait for a slot; the returned release hands it straight to the next in line. */
async function slot(): Promise<() => void> {
  if (inFlight < MAX_IN_FLIGHT) inFlight++;
  else await new Promise<void>((r) => waiting.push(r));
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const next = waiting.shift();
    if (next) next();
    else inFlight--;
  };
}

/** Requests holding or waiting for a slot (tests). */
export const queued = () => ({ inFlight, waiting: waiting.length });

/** fetch through the in-flight cap, trying a throttled response again (when `retry`)
 *  until it is not throttled, RETRY_TRIES are used, or the next wait would pass
 *  RETRY_CAP_MS from the start. The last response is returned as is: the caller's error
 *  handling sees it. */
export async function fetchRetrying(
  url: string,
  init: RequestInit | undefined,
  retry: boolean,
  deps: RetryDeps = {},
): Promise<Response> {
  const {
    fetch: send = (u: string, i?: RequestInit) => globalThis.fetch(u, i),
    sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
    random = Math.random,
    now = Date.now,
  } = deps;
  const start = now();
  for (let attempt = 0; ; attempt++) {
    // the slot covers the request, not the backoff: a waiting retry frees it
    const release = await slot();
    let res: Response;
    try {
      res = await send(url, init);
    } finally {
      release();
    }
    if (!retry || attempt + 1 >= RETRY_TRIES) return res;
    const wait = await throttleWait(res, attempt, random, now);
    if (wait === null || now() - start + wait > RETRY_CAP_MS) return res;
    await sleep(wait);
  }
}
