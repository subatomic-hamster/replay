// D-87 evidence: how many API requests the TV (web build, real HTTP client) has in flight
// at once when a game opens, from the browser's network log. Run against a services/api
// (REPLAY_TV_API=<base>) and a processed game (REPLAY_TV_EVIDENCE_GAME). The cloud API runs
// on Lambda with an account concurrency of 10: one Watch open used to send 9 at once.
// The log goes to REPLAY_TV_EVIDENCE_DIR/watch-open-requests.json.
import { expect, test } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { openWatch } from "../e2e/helpers";

const API = process.env.REPLAY_TV_API ?? "mock";
const OUT =
  process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence-watchopen";
const GAME = process.env.REPLAY_TV_EVIDENCE_GAME ?? "g_mock01";
const WINDOW_MS = 12_000;

test("WATCHOPEN in-flight API requests while a game opens", async ({
  page,
}) => {
  test.skip(API === "mock", "needs a running API");
  test.setTimeout(60_000);
  const t0 = Date.now();
  const log: { path: string; start: number; end?: number; status?: number }[] =
    [];
  const open = new Map<object, (typeof log)[number]>();
  let inFlight = 0;
  let peak = 0;
  // API calls and the /media JSON (tracks chunks: on AWS a Lambda request each, a 302
  // to S3); not the video's byte ranges or images (S3 directly on AWS)
  const api = (u: string) =>
    u.startsWith(API) && !/\.(mp4|jpg|jpeg|png|webp)(\?|$)/.test(u);
  page.on("request", (r) => {
    if (!api(r.url()) || r.method() === "OPTIONS") return;
    const row = { path: new URL(r.url()).pathname, start: Date.now() - t0 };
    log.push(row);
    open.set(r, row);
    peak = Math.max(peak, ++inFlight);
  });
  const done = (r: object, status?: number) => {
    const row = open.get(r);
    if (!row) return;
    open.delete(r);
    row.end = Date.now() - t0;
    row.status = status;
    inFlight--;
  };
  page.on("requestfinished", async (r) =>
    done(r, (await r.response())?.status()),
  );
  page.on("requestfailed", (r) => done(r));

  await openWatch(page, GAME);
  await expect(page.getByTestId("watch")).toBeVisible();
  await page.waitForTimeout(WINDOW_MS - (Date.now() - t0));

  // the most requests that were ever open together, from the log itself
  const edges = log.flatMap((r) => [
    [r.start, 1],
    [r.end ?? WINDOW_MS, -1],
  ]);
  edges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  let maxOpen = 0;
  for (const [, d] of edges) maxOpen = Math.max(maxOpen, (cur += d));
  mkdirSync(OUT, { recursive: true });
  const summary = {
    game: GAME,
    requests: log.length,
    peak_in_flight: maxOpen,
    log,
  };
  writeFileSync(
    path.join(OUT, "watch-open-requests.json"),
    JSON.stringify(summary, null, 1),
  );
  console.log(
    `requests=${log.length} peak_in_flight=${maxOpen} (live counter ${peak})\n` +
      log
        .map(
          (r) =>
            `  ${String(r.start).padStart(5)}–${String(r.end ?? "").padStart(5)} ms  ${r.status ?? "-"}  ${r.path}`,
        )
        .join("\n"),
  );
});
