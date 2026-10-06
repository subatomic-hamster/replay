// M13 phone companion: tap-to-clip ("Replay, clip that" from the phone) and search with
// "Play on TV". The session socket is faked with page.routeWebSocket, so each side is
// tested alone against the protocol (the live project pairs a real TV and phone through
// the API's relay): TV → phone `now` {game_id, title, t} once a second; phone → TV
// `clip` {label} after its POST /games/{id}/triggers, and `seek` {t} for a search hit.
import { expect, test, type WebSocketRoute } from "@playwright/test";
import { GAME_ID, mockCalls, openWatch, video } from "./helpers";

test("S-48 phone: Clip that posts a tap at the TV's media time and tells the TV", async ({
  page,
}) => {
  const fromPhone: Record<string, unknown>[] = [];
  const tv: WebSocketRoute[] = [];
  await page.routeWebSocket(/\/sessions\/4821$/, (ws) => {
    tv.push(ws);
    ws.onMessage((m) => fromPhone.push(JSON.parse(String(m))));
  });
  await page.goto("/companion/4821");
  await expect(page.getByTestId("companion-status")).toHaveAttribute("data-state", "open");
  // nothing on the TV yet: nothing to clip
  await expect(page.getByTestId("companion-clip")).toBeDisabled();

  expect(tv.length).toBeGreaterThan(0);
  // the live socket is the last one (StrictMode opens and drops one first in dev)
  tv[tv.length - 1].send(JSON.stringify({ type: "now", game_id: GAME_ID, title: "Mock game", t: 9.6 }));
  await expect(page.getByTestId("companion-now")).toHaveAttribute("data-game-id", GAME_ID);
  await expect(page.getByTestId("companion-now")).toContainText("0:09.6");

  await page.getByTestId("companion-clip").click();
  // D-50: the play that just ended (pl_m2, 5.5–9.5 s) ± 1 s
  await expect(page.getByTestId("companion-clip-result")).toHaveText("Clip saved · 0:04.5–0:10.5");
  const post = (await mockCalls(page)).find((c) => c.path === `/games/${GAME_ID}/triggers`);
  expect(post).toEqual({ method: "POST", path: `/games/${GAME_ID}/triggers`, body: { t: 9.6 } });
  await expect.poll(() => fromPhone).toContainEqual({ type: "clip", label: "Clip saved · 0:04.5–0:10.5" });

  // Search runs on the phone; "Play on TV" sends the hit's start.
  await page.getByTestId("companion-search").fill("Marcus — all shots");
  await page.getByTestId("companion-search-go").click();
  const hits = page.getByTestId("companion-hit");
  await expect(hits).toHaveCount(4);
  const t0 = Number(await hits.first().getAttribute("data-t-start"));
  await hits.first().getByTestId("companion-play").click();
  await expect.poll(() => fromPhone).toContainEqual({ type: "seek", t: t0 });
});

test("S-48 TV: reports what is on screen, plays a pushed hit, toasts a phone clip", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("replay.session", JSON.stringify({ id: "s_e2e", code: "4821" })),
  );
  const fromTv: { type: string; game_id?: string; t?: number }[] = [];
  const phone: WebSocketRoute[] = [];
  await page.routeWebSocket(/\/sessions\/s_e2e$/, (ws) => {
    phone.push(ws);
    ws.onMessage((m) => fromTv.push(JSON.parse(String(m))));
  });
  await openWatch(page);

  await expect
    .poll(() => fromTv.find((m) => m.type === "now"), { timeout: 5_000 })
    .toMatchObject({ type: "now", game_id: GAME_ID });
  const ws = phone[phone.length - 1];

  ws.send(JSON.stringify({ type: "seek", t: 12 }));
  await expect.poll(async () => (await video(page))?.currentTime ?? 0).toBeGreaterThan(11.9);
  await expect.poll(async () => (await video(page))?.paused).toBe(false);

  ws.send(JSON.stringify({ type: "clip", label: "Clip saved · 0:04.5–0:10.5" }));
  await expect(page.getByTestId("toast")).toHaveText("Clip saved · 0:04.5–0:10.5");
  await expect(page.getByTestId("toast")).toHaveCount(0, { timeout: 6_000 });
});
