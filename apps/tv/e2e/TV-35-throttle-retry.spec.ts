// D-87: the cloud API's Lambda has an account concurrency of 10. Throttled requests (429,
// or a 503 that says so) are tried again with jittered backoff within ~4 s, only when
// safe to repeat; at most 4 requests are in flight; Watch sends what the first frame does
// not need after it; a route the server cannot serve (503 "not available") is not asked
// again. Unit tests of packages/tv-core/src/retry.ts and the client, then the TV.
import { expect, test } from "@playwright/test";
import { createHttpApi } from "../../../packages/tv-core/src/api";
import {
  MAX_IN_FLIGHT,
  RETRY_CAP_MS,
  RETRY_TRIES,
  fetchRetrying,
  idempotent,
  queued,
  throttleWait,
} from "../../../packages/tv-core/src/retry";
import { GAME_ID, mockCalls, openWatch, video } from "./helpers";

/** A scripted fetch and a fake clock: sleeping moves the clock. */
function rig(responses: (() => Response)[]) {
  let clock = 0;
  const sent: string[] = [];
  const waits: number[] = [];
  return {
    sent,
    waits,
    deps: {
      fetch: async (u: string) => {
        sent.push(u);
        return (
          responses[sent.length - 1] ?? responses[responses.length - 1]
        )();
      },
      sleep: async (ms: number) => {
        waits.push(ms);
        clock += ms;
      },
      random: () => 0.5,
      now: () => clock,
    },
  };
}
const throttled =
  (headers: Record<string, string> = {}) =>
  () =>
    new Response('{"Message":"Rate Exceeded."}', { status: 429, headers });
const ok = () => new Response("[]", { status: 200 });

test("TV-35 retry: 429s are tried again with backoff, Retry-After honoured, then the answer", async () => {
  const r = rig([throttled({ "Retry-After": "1" }), throttled(), ok]);
  const res = await fetchRetrying("u", undefined, true, r.deps);
  expect(res.status).toBe(200);
  expect(r.sent).toHaveLength(3);
  // Retry-After: 1 s plus a little jitter; then the jittered exponential step
  expect(r.waits[0]).toBeGreaterThanOrEqual(1000);
  expect(r.waits[0]).toBeLessThan(1100);
  expect(r.waits[1]).toBeGreaterThan(100);
  expect(r.waits[1]).toBeLessThan(100 + 300 * 2);
});

test("TV-35 retry: gives up within the cap and returns the throttle for the usual error", async () => {
  const always = rig([throttled()]);
  const res = await fetchRetrying("u", undefined, true, always.deps);
  expect(res.status).toBe(429);
  expect(always.sent.length).toBeLessThanOrEqual(RETRY_TRIES);
  expect(always.waits.reduce((a, b) => a + b, 0)).toBeLessThanOrEqual(
    RETRY_CAP_MS,
  );
  // a Retry-After past the cap is not waited for
  const long = rig([throttled({ "Retry-After": "30" }), ok]);
  expect((await fetchRetrying("u", undefined, true, long.deps)).status).toBe(
    429,
  );
  expect(long.sent).toHaveLength(1);
});

test("TV-35 retry: only throttles, only when safe to repeat", async () => {
  // our API's own 503 (no replay_render) is an answer, not a throttle
  const own = rig([
    () =>
      new Response('{"detail":"replay_render is not available"}', {
        status: 503,
      }),
    ok,
  ]);
  expect((await fetchRetrying("u", undefined, true, own.deps)).status).toBe(
    503,
  );
  expect(own.sent).toHaveLength(1);
  // a 503 whose body says throttle is tried again
  const lambda = rig([
    () => new Response("Rate Exceeded.", { status: 503 }),
    ok,
  ]);
  expect((await fetchRetrying("u", undefined, true, lambda.deps)).status).toBe(
    200,
  );
  // a write that is not idempotent is sent once
  const post = rig([throttled(), ok]);
  expect((await fetchRetrying("u", undefined, false, post.deps)).status).toBe(
    429,
  );
  expect(post.sent).toHaveLength(1);
  expect([undefined, "GET", "PATCH", "PUT", "DELETE"].every(idempotent)).toBe(
    true,
  );
  expect(idempotent("POST")).toBe(false);
  expect(await throttleWait(new Response("x", { status: 500 }), 0)).toBeNull();
});

test("TV-35 at most MAX_IN_FLIGHT requests in flight; the rest go in order", async () => {
  const opened: string[] = [];
  const finish: (() => void)[] = [];
  let peak = 0;
  const deps = {
    fetch: (u: string) =>
      new Promise<Response>((resolve) => {
        opened.push(u);
        peak = Math.max(peak, queued().inFlight);
        finish.push(() => resolve(ok()));
      }),
  };
  const all = Array.from({ length: 10 }, (_, i) =>
    fetchRetrying(`u${i}`, undefined, true, deps),
  );
  await new Promise((r) => setTimeout(r, 10));
  expect(opened).toHaveLength(MAX_IN_FLIGHT);
  expect(queued().waiting).toBe(10 - MAX_IN_FLIGHT);
  while (finish.length) {
    finish.shift()?.();
    await new Promise((r) => setTimeout(r, 1));
  }
  await Promise.all(all);
  expect(opened).toEqual(Array.from({ length: 10 }, (_, i) => `u${i}`));
  expect(peak).toBe(MAX_IN_FLIGHT);
  expect(queued()).toEqual({ inFlight: 0, waiting: 0 });
});

test("TV-35 client: hype and rallies the server cannot serve are not asked again", async () => {
  const real = globalThis.fetch;
  const sent: string[] = [];
  globalThis.fetch = (async (u: string) => {
    sent.push(String(u));
    return new Response(
      '{"detail":"replay_render is not available: No module named \'replay_render\'"}',
      { status: 503 },
    );
  }) as typeof fetch;
  try {
    const api = createHttpApi("http://api.test");
    for (let i = 0; i < 3; i++) {
      await expect(api.getHype("g1")).rejects.toMatchObject({ status: 503 });
      await expect(api.getRallies("g1")).rejects.toMatchObject({ status: 503 });
    }
    expect(sent).toEqual([
      "http://api.test/games/g1/hype",
      "http://api.test/games/g1/rallies",
    ]);
    // another game is its own question
    await expect(api.getHype("g2")).rejects.toMatchObject({ status: 503 });
    expect(sent).toHaveLength(3);
  } finally {
    globalThis.fetch = real;
  }
});

const BASE = "http://10.0.0.5:8000";
const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET, OPTIONS",
};

test("TV-35 a throttled API is tried again behind the spinner, then answers", async ({
  page,
}) => {
  let gets = 0;
  await page.route(`${BASE}/games`, (route) => {
    if (route.request().method() === "OPTIONS")
      return route.fulfill({ status: 204, headers: cors });
    gets++;
    return gets <= 2
      ? route.fulfill({
          status: 429,
          body: '{"Message":"Rate Exceeded."}',
          headers: cors,
        })
      : route.fulfill({ json: [{ id: "g1" }, { id: "g2" }], headers: cors });
  });
  await page.addInitScript(
    (b) => localStorage.setItem("replay.apiBase", b),
    BASE,
  );
  await page.goto("/tv/settings");
  // the real HTTP client (Settings' connection test), not the mock
  await expect(page.getByTestId("settings-check")).toHaveAttribute(
    "data-state",
    "ok",
    {
      timeout: 6_000,
    },
  );
  await expect(page.getByTestId("settings-check")).toContainText(
    "Connected · 2 games",
  );
  expect(gets).toBe(3);
});

test("TV-35 throttled past the cap: the usual error, within about 4 s", async ({
  page,
}) => {
  let gets = 0;
  await page.route(`${BASE}/games`, (route) => {
    if (route.request().method() === "OPTIONS")
      return route.fulfill({ status: 204, headers: cors });
    gets++;
    return route.fulfill({
      status: 429,
      body: '{"Message":"Rate Exceeded."}',
      headers: cors,
    });
  });
  await page.addInitScript(
    (b) => localStorage.setItem("replay.apiBase", b),
    BASE,
  );
  const t0 = Date.now();
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings-checking")).toBeVisible();
  await expect(page.getByTestId("settings-check")).toHaveAttribute(
    "data-state",
    "error",
    {
      timeout: 8_000,
    },
  );
  expect(Date.now() - t0).toBeLessThan(RETRY_CAP_MS + 3_000);
  await expect(page.getByTestId("settings-check")).toContainText(
    "Not reachable",
  );
  expect(gets).toBeGreaterThan(1);
  expect(gets).toBeLessThanOrEqual(RETRY_TRIES);
});

test("TV-35 Watch opens with the game, renditions and moments; the extras follow the first frame", async ({
  page,
}) => {
  await openWatch(page, GAME_ID); // the video has its first frame (readyState >= 2)
  expect((await video(page))?.readyState).toBeGreaterThanOrEqual(2);
  const extras = ["/hype", "/commentary", "/rallies", "/replays"].map(
    (s) => `/games/${GAME_ID}${s}`,
  );
  await expect
    .poll(
      async () =>
        (await mockCalls(page)).filter((c) => extras.includes(c.path)).length,
    )
    .toBe(extras.length);
  const calls = (await mockCalls(page)).map((c) => c.path);
  const firstExtra = Math.min(...extras.map((p) => calls.indexOf(p)));
  const before = calls.slice(0, firstExtra);
  for (const p of ["", "/renditions", "/moments"])
    expect(before).toContain(`/games/${GAME_ID}${p}`);
});
