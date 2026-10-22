// The whole product against the real services/api (REPLAY_PIPELINE=fake), not the mock.
// Serial on purpose: one API process, one data dir, and the tests below reuse the game
// that S-01 uploads.
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { menuTo } from "../e2e/helpers";

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(here, "../../..");
const FIXTURE = path.join(REPO, "services/api/fixtures/tiny.mp4");
const API = "http://localhost:8000";

/** Landmarks projected from courtcam's basketball_half template onto a 1280x720 frame
 *  (the same values services/api/tests/conftest.py calibrates with: ~0.02 px error).
 *  The *order* is not asserted from here — the profile owns it (see `landmarkOrder`). */
const LANDMARKS: Record<string, [number, number]> = {
  corner_nl: [180, 660],
  corner_nr: [1100, 660],
  corner_fl: [430, 300],
  corner_fr: [860, 300],
  rim: [641.1, 583.2],
};

let gameId = "";

/** The click order the uploader walks, straight from the profile. Hardcoding it here
 *  meant the spec asserted "rim" for point 5 and broke whenever a profile reordered its
 *  landmarks — the contract is `GET /sports` -> `landmarks` (D-13), so read it. */
async function landmarkOrder(page: Page, sport: string): Promise<string[]> {
  const names = await page.evaluate(
    async ([api, id]) => {
      const sports: { id: string; landmarks?: string[] }[] = await fetch(
        `${api}/sports`,
      ).then((r) => r.json());
      return (sports.find((s) => s.id === id) ?? sports[0])?.landmarks ?? [];
    },
    [API, sport] as const,
  );
  expect(
    names.length,
    "GET /sports carries the landmark click order",
  ).toBeGreaterThanOrEqual(4);
  return names;
}

test.describe.configure({ mode: "serial" });

async function video(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return (
      v && {
        currentTime: v.currentTime,
        paused: v.paused,
        readyState: v.readyState,
      }
    );
  });
}

async function waitForVideo(page: Page) {
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
}

test("L-00 a fresh data dir shows the empty library", async ({ page }) => {
  await page.goto("/tv");
  await expect(page.getByTestId("library-empty")).toBeVisible();
  await expect(page.getByTestId("game-card")).toHaveCount(0);
});

test("S-01 upload -> calibrate -> process -> watch -> follow -> highlights -> review", async ({
  page,
}) => {
  test.setTimeout(300_000); // the fake pipeline still transcodes the upload with ffmpeg

  // --- create ------------------------------------------------------------
  await page.goto("/upload");
  await expect(page.getByTestId("sport-option-basketball")).toBeVisible();
  await page.getByTestId("game-title-input").fill("Live run");
  await page.getByTestId("create-game").click();
  await page.waitForURL(/\/upload\/g_[a-z0-9]+/);
  gameId = new URL(page.url()).pathname.split("/")[2];

  // --- upload (XHR PUT with the file's own Content-Type) ------------------
  await page.getByTestId("file-input").setInputFiles(FIXTURE);
  await expect(page.getByTestId("upload-progress")).toBeVisible();
  await expect(page.getByTestId("upload-done")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByTestId("upload-progress")).toHaveJSProperty(
    "value",
    100,
  );
  await page.getByTestId("go-calibrate").click();

  // --- calibrate ---------------------------------------------------------
  const img = page.getByTestId("calib-image");
  await expect(img).toBeVisible();
  const frame = await img.evaluate((el: HTMLImageElement) => ({
    w: el.naturalWidth,
    h: el.naturalHeight,
  }));
  expect(frame.w).toBeGreaterThan(0); // D-14: the frame exists before processing

  const box = (await img.boundingBox())!;
  const order = await landmarkOrder(page, "basketball");
  for (const [i, name] of order.entries()) {
    const [x, y] = LANDMARKS[name] ?? [];
    expect(
      x,
      `this spec has a pixel for every landmark the profile asks for (${name})`,
    ).toBeDefined();
    await expect(page.getByTestId("calib-prompt")).toHaveAttribute(
      "data-target",
      name,
    );
    await expect(page.getByTestId("calib-prompt")).toContainText(
      `point ${i + 1} of ${order.length}`,
    );
    await page.mouse.click(
      box.x + (x / frame.w) * box.width,
      box.y + (y / frame.h) * box.height,
    );
    await expect(page.getByTestId(`landmark-${name}`)).toBeVisible();
  }

  const error = page.getByTestId("calib-error");
  await expect(error).toHaveAttribute("data-ok", "true");
  const px = Number((await error.textContent())!.replace(" px", ""));
  expect(px).toBeLessThan(5);

  // --- process -----------------------------------------------------------
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  await page.getByTestId("start-processing").click();
  await page.waitForURL(new RegExp(`/upload/${gameId}/status`));
  // S-08 / D-9: while the job runs, GET /games/{id} merges the job record's stage state,
  // so the status page shows exactly one stage `running` with the later ones `pending`.
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const status = document.querySelector(
            '[data-testid="game-status"]',
          )?.textContent;
          const states = [
            ...document.querySelectorAll('[data-testid^="stage-"]'),
          ]
            .map((el) => el.getAttribute("data-state"))
            .join(",");
          return `${status} ${states}`;
        }),
      { timeout: 120_000 },
    )
    // exactly one running stage, everything before it done, everything after pending
    .toMatch(/^processing (done,)*running(,pending)*$/);
  for (const stage of ["ingest", "detect", "track", "render", "label"]) {
    await expect(page.getByTestId(`stage-${stage}`)).toHaveAttribute(
      "data-state",
      /done|partial/,
      {
        timeout: 240_000,
      },
    );
  }
  await expect(page.getByTestId("game-status")).toHaveText("ready");

  // --- library -----------------------------------------------------------
  await page.goto("/tv");
  const card = page.locator(
    `[data-testid=game-card][data-game-id="${gameId}"]`,
  );
  await expect(card).toBeVisible();
  await expect(card.getByTestId("game-status")).toHaveText("ready");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}$`));

  // --- watch: play, then pause into select mode --------------------------
  await waitForVideo(page);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await expect
    .poll(async () => (await video(page))?.currentTime ?? 0)
    .toBeGreaterThan(0.3);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);

  // boxes come from the real tracks chunks served out of the game dir
  const boxes = page.locator('[data-testid^="select-box-"]');
  await expect(boxes.first()).toBeVisible();
  await expect(boxes).toHaveCount(2);

  // --- follow ------------------------------------------------------------
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          getComputedStyle(
            document.querySelector('[data-testid="player-transform"]')!,
          ).transform,
      ),
    )
    .not.toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);

  // --- highlights (reached with the D-pad, not a URL) ---------------------
  await menuTo(page, "nav-highlights");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights`));

  // The chips come from the sport profile; take the "all shots" one.
  const chips = page.getByTestId("query-chip");
  await expect(chips.first()).toBeVisible();
  const labels = await chips.evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-chip") ?? ""),
  );
  const target = labels.findIndex((l) => /all shots/i.test(l));
  expect(
    target,
    `no "all shots" chip in ${JSON.stringify(labels)}`,
  ).toBeGreaterThanOrEqual(0);
  for (let i = 0; i < target; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("reel-clip").first()).toBeVisible();
  const clips = await page.getByTestId("reel-clip").count();
  expect(clips).toBeGreaterThan(0);
  await expect(page.getByTestId("clip-counter")).toContainText(`/${clips}`);

  await waitForVideo(page);
  const tStart = Number(
    await page.getByTestId("reel-clip").first().getAttribute("data-t-start"),
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  expect(
    Math.abs(((await video(page))?.currentTime ?? 0) - tStart),
  ).toBeLessThan(1.5);

  // --- review: answer the first GET /review/queue question (D-48) ----------
  const queue = await (
    await page.request.get(`${API}/games/${gameId}/review/queue`)
  ).json();
  const first = queue.questions[0];
  expect(
    first?.event_id,
    "the fake game queues an event question first",
  ).toBeTruthy();
  await page.goto(`/tv/${gameId}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toHaveAttribute("data-event-id", first.event_id);
  await page.keyboard.press("Enter"); // the first option ("Made" / "Yes")
  await expect(item.or(page.getByTestId("review-empty"))).not.toHaveAttribute(
    "data-event-id",
    first.event_id,
  );

  // PATCH actually persisted: re-read events.json off the API
  const events = await (
    await page.request.get(`${API}/media/games/${gameId}/events.json`)
  ).json();
  const patched = events.events.find(
    (e: { id: string }) => e.id === first.event_id,
  );
  expect(patched).toMatchObject(first.options[0].body);

  // --- bookmark ----------------------------------------------------------
  await page.goto(`/tv/${gameId}`);
  await waitForVideo(page);
  const before = await page.getByTestId("event-marker").count();
  await page.keyboard.press("b");
  await expect(page.getByTestId("event-marker")).toHaveCount(before + 1);
  const after = await (
    await page.request.get(`${API}/media/games/${gameId}/events.json`)
  ).json();
  expect(
    after.events.filter((e: { type: string }) => e.type === "bookmark"),
  ).toHaveLength(2);
});

test("E-22 an unreachable API shows the error banner, not a white page", async ({
  page,
}) => {
  await page.route(`${API}/games`, (route) => route.abort("connectionrefused"));
  await page.goto("/tv");
  await expect(page.getByTestId("api-error")).toBeVisible();
  await expect(page.getByTestId("game-card")).toHaveCount(0);
});

test("D-3 the wide MP4 is range-seekable and the player settles on the target", async ({
  page,
}) => {
  expect(gameId, "S-01 must have run first").not.toBe("");

  const wide = `${API}/media/games/${gameId}/media/wide.mp4`;
  const ranged = await page.request.get(wide, {
    headers: { Range: "bytes=0-99" },
  });
  expect(ranged.status()).toBe(206);
  expect((await ranged.body()).length).toBe(100);

  await page.goto(`/tv/${gameId}`);
  await waitForVideo(page);
  await page.evaluate(() => {
    document.querySelector<HTMLVideoElement>(
      '[data-testid="video"]',
    )!.currentTime = 10;
  });
  await expect
    .poll(async () => {
      const v = await video(page);
      return v && v.readyState >= 2 ? Math.abs(v.currentTime - 10) : 99;
    })
    .toBeLessThan(0.5);
});

// S-31 / H4 — phone companion over the session WebSocket. Two pages in one context
// (separate tabs, so separate sessionStorage); the WS fan-out is in-process, so the mock
// cannot stand in for it. Lives here because the live project runs one file serially.
test("S-31 a phone query moves the TV to the matching highlights", async ({
  page,
  context,
}) => {
  expect(gameId, "S-01 must have run first").not.toBe("");

  // --- TV: reach the pairing code with the remote only (`p` on Highlights) ---------
  await page.goto(`/tv/${gameId}/highlights`);
  await expect(page.getByTestId("query-chip").first()).toBeVisible();
  await page.keyboard.press("p");
  await page.waitForURL(/\/tv\/pair\?game=/);
  await expect(page.getByTestId("pair-code")).toHaveText(/^\d{4}$/);
  const code = (await page.getByTestId("pair-code").textContent())!.trim();

  // --- phone: enter the code, then send a query ------------------------------------
  const phone = await context.newPage();
  await phone.goto("/companion");
  await phone.getByTestId("companion-code-input").fill(code);
  await phone.getByTestId("companion-connect").click();
  await phone.waitForURL(new RegExp(`/companion/${code}`));
  await expect(phone.getByTestId("companion-status")).toHaveAttribute(
    "data-state",
    "open",
  );

  await phone.getByTestId("companion-query").fill("Marcus — all shots");
  await phone.getByTestId("companion-send").click();
  await expect(phone.getByTestId("companion-sent")).toContainText("Marcus");

  // --- TV: jumps to the results with no remote input (within 2 s per S-31) ---------
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights\\?q=`), {
    timeout: 5000,
  });
  await expect(page.getByTestId("query-interpretation")).toBeVisible();
  await expect(page.getByTestId("query-interpretation")).toContainText(
    "Marcus",
  );
  await expect(page.getByTestId("reel-clip").first()).toBeVisible();

  // --- a second query lands on the Highlights screen itself, still no remote --------
  await phone.getByTestId("companion-query").fill("misses");
  await phone.getByTestId("companion-send").click();
  await expect(page.getByTestId("query-interpretation")).toContainText(
    "missed shots",
    {
      timeout: 5000,
    },
  );
  await phone.close();
});

// M13 — "Replay, clip that" from the phone and "Play on TV", through the real relay and
// the real POST /games/{id}/triggers. The fake game has no plays.json, so the tap is
// stored but cuts no clip (D-50), and its search has no index, so it is the keyword
// fallback — both are the honest answers for this fixture.
test("S-48 live: the phone clips at the TV's media time and sends a search hit to the TV", async ({
  page,
  context,
}) => {
  expect(gameId, "S-01 must have run first").not.toBe("");
  await page.goto(`/tv/pair?game=${gameId}`);
  await expect(page.getByTestId("pair-code")).toHaveText(/^\d{4}$/);
  const code =
    (await page.getByTestId("pair-code").textContent())?.trim() ?? "";
  await page.goto(`/tv/${gameId}?t=4`); // same tab: the session survives in sessionStorage
  await waitForVideo(page);

  const phone = await context.newPage();
  await phone.goto(`/companion/${code}`);
  await expect(phone.getByTestId("companion-status")).toHaveAttribute(
    "data-state",
    "open",
  );
  await expect(phone.getByTestId("companion-now")).toHaveAttribute(
    "data-game-id",
    gameId,
    {
      timeout: 5000,
    },
  );
  await phone.getByTestId("companion-clip").click();
  await expect(phone.getByTestId("companion-clip-result")).toHaveText(
    /^(Clip|Tap) saved/,
  );
  const label =
    (await phone.getByTestId("companion-clip-result").textContent()) ?? "";
  await expect(page.getByTestId("toast")).toHaveText(label);
  const triggers = await (
    await page.request.get(`${API}/games/${gameId}/triggers`)
  ).json();
  const tap = triggers.triggers.find((t: { type: string }) => t.type === "tap");
  expect(tap).toMatchObject({ type: "tap", source: "user" });
  expect(tap.t).toBeGreaterThanOrEqual(3);

  await phone.getByTestId("companion-search").fill("all shots");
  await phone.getByTestId("companion-search-go").click();
  const hit = phone.getByTestId("companion-hit").first();
  await expect(hit).toBeVisible();
  const t0 = Number(await hit.getAttribute("data-t-start"));
  await hit.getByTestId("companion-play").click();
  await expect
    .poll(async () => Math.abs(((await video(page))?.currentTime ?? -9) - t0))
    .toBeLessThan(1.5);
  await phone.close();
});

test("S-31/AC-13 an unpaired code reports a closed session instead of hanging", async ({
  page,
}) => {
  // Pairing codes are always four digits, so this one can never resolve (D-16).
  await page.goto("/companion/s_nope");
  await expect(page.getByTestId("companion-status")).toHaveAttribute(
    "data-state",
    "closed",
  );
  await expect(page.getByTestId("companion-error")).toBeVisible();
  await expect(page.getByTestId("companion-send")).toBeDisabled();
});

// M10 against the real profiles routes (D-58), on the game S-01 uploaded. The profile is
// made through the API in this run's temp data dir and named after a roster player, so the
// TV offers it as a same-name suggestion; the photo is a synthetic 1x1 PNG. The fake
// pipeline has no face model, so enrollment answers 503/422 and the page must say so.
const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==",
  "base64",
);

async function profileTab(
  page: Page,
  name: "stats" | "card" | "reel" | "links",
) {
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "tabs",
  );
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  for (let i = 0; i < ["stats", "card", "reel", "links"].indexOf(name); i++)
    await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", name);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "body",
  );
}

test("S-53 live profiles: suggestion → link, stat correction, card PNG, reel, phone photo, face consent", async ({
  page,
}) => {
  test.setTimeout(120_000);
  expect(gameId).not.toBe("");
  const game = await (await page.request.get(`${API}/games/${gameId}`)).json();
  const player = (game.players as { id: string; name: string | null }[]).find(
    (p) => p.name,
  );
  if (!player?.name) throw new Error("the fixture roster has no named player");
  const created = await page.request.post(`${API}/profiles`, {
    data: { name: player.name },
  });
  expect(created.status()).toBe(201);
  const id: string = (await created.json()).profile_id;
  expect(id).toMatch(/^pr_[0-9a-f]{12}$/);

  // Players → profile → Links: the same-name suggestion, accepted with the D-pad
  await page.goto("/tv/players");
  await expect(
    page.locator(`[data-testid="profile-card"][data-profile-id="${id}"]`),
  ).toBeVisible();
  await page.goto(`/tv/players/${id}`);
  await profileTab(page, "links");
  const sug = page.locator(
    `[data-testid="suggestion-row"][data-game-id="${gameId}"][data-player-id="${player.id}"]`,
  );
  await expect(sug).toHaveAttribute("data-face", "false");
  await expect(sug.getByTestId("suggestion-reason")).toContainText(
    "Same name tag",
  );
  await expect(
    page.locator('[data-testid="suggestion-row"][data-face="true"]'),
  ).toHaveCount(0);
  for (
    let i = 0;
    i < 8 && (await sug.getAttribute("data-focused")) !== "true";
    i++
  )
    await page.keyboard.press("ArrowDown");
  await expect(sug.getByTestId("suggestion-accept")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(
    page.locator(`[data-testid="link-row"][data-game-id="${gameId}"]`),
  ).toBeVisible();
  let doc = await (await page.request.get(`${API}/profiles/${id}`)).json();
  expect(doc.linked).toEqual([{ game_id: gameId, player_id: player.id }]);

  // Stats: the second row (the first is `games`), one step up, saved as an edit
  await page.keyboard.press("Escape");
  await profileTab(page, "stats");
  const sport = await page.getByTestId("stats-tab").getAttribute("data-sport");
  const rows = page.getByTestId("stat-row");
  await expect(rows.first()).toHaveAttribute("data-key", "games");
  const row = rows.nth(1);
  for (
    let i = 0;
    i < 3 && (await row.getAttribute("data-focused")) !== "true";
    i++
  ) {
    await page.keyboard.press("ArrowDown"); // (past the sport pills when there are several)
  }
  await expect(row).toHaveAttribute("data-focused", "true");
  const key = (await row.getAttribute("data-key")) ?? "";
  const before = Number(await row.getAttribute("data-value"));
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("data-edited", "true");
  await expect(row).toHaveAttribute(
    "data-value",
    String(Math.round(before) + 1),
  );
  await expect(row.getByTestId("stat-edited")).toContainText(`auto ${before}`);
  doc = await (await page.request.get(`${API}/profiles/${id}`)).json();
  expect(doc.stats_by_sport[sport ?? ""].edited).toContain(key);
  expect(doc.stats_by_sport[sport ?? ""].stats[key]).toBe(
    Math.round(before) + 1,
  );

  // Card: Enter renders the PNG on the server; the JSON fields come with it
  await page.keyboard.press("Escape");
  await profileTab(page, "card");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-tab")).toHaveAttribute(
    "data-rendered",
    "true",
    { timeout: 30_000 },
  );
  await expect(page.getByTestId("card-png")).toHaveAttribute(
    "src",
    new RegExp(`/media/profiles/${id}/card\\.png\\?v=`),
  );
  await expect
    .poll(
      () =>
        page
          .getByTestId("card-png")
          .evaluate((el) => (el as HTMLImageElement).naturalWidth),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0);
  await expect(page.getByTestId("card-title")).toContainText(player.name);

  // Reel: whatever plays the fake pipeline gave this player, playable in order
  await page.keyboard.press("Escape");
  await profileTab(page, "reel");
  await expect(
    page
      .locator(
        '[data-testid="reel-item"], [data-testid="reel-empty"], [data-testid="reel-note"]',
      )
      .first(),
  ).toBeVisible();
  await expect(page.getByTestId("reel-note")).toHaveCount(0); // GET /reel answered
  if (await page.getByTestId("reel-item").count()) {
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reel-counter")).toHaveAttribute(
      "data-index",
      "1",
    );
    await expect(page.getByTestId("reel-counter")).toHaveAttribute(
      "data-game-id",
      gameId,
    );
    await waitForVideo(page);
  } else {
    await expect(page.getByTestId("reel-empty")).toBeVisible();
  }

  // Phone: photo upload (re-encoded by the API) and the consent-gated face enrollment
  await page.goto(`/profiles/${id}`);
  await expect(page.getByTestId("profile-edit")).toBeVisible();
  await page.getByTestId("profile-photo-input").setInputFiles({
    name: "synthetic.png",
    mimeType: "image/png",
    buffer: PNG_1PX,
  });
  await expect(page.getByTestId("profile-note")).toHaveText("Photo saved");
  await expect(page.getByTestId("avatar").first()).toHaveAttribute(
    "data-photo",
    "true",
  );
  await expect
    .poll(() =>
      page
        .locator('[data-testid="avatar"] img')
        .first()
        .evaluate((el) => (el as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);

  await expect(page.getByTestId("face-enroll")).toBeDisabled();
  await expect(page.getByTestId("face-photos")).toBeDisabled();
  await page.getByTestId("face-consent").check();
  await page.getByTestId("face-photos").setInputFiles({
    name: "synthetic.png",
    mimeType: "image/png",
    buffer: PNG_1PX,
  });
  await page.getByTestId("face-enroll").click();
  // no face model in the fake pipeline (503), or no face in a 1x1 PNG (422): never enrolled
  await expect(page.getByTestId("face-note")).toHaveText(/^Not enrolled: /);
  await expect(page.getByTestId("face-section")).toHaveAttribute(
    "data-enrolled",
    "false",
  );
  // the API itself refuses without consent
  const refused = await page.request.post(`${API}/profiles/${id}/face`, {
    multipart: {
      consent: "false",
      photos: { name: "synthetic.png", mimeType: "image/png", buffer: PNG_1PX },
    },
  });
  expect(refused.status()).toBe(400);
  const forgot = await page.request.delete(`${API}/profiles/${id}/face`);
  expect(forgot.ok()).toBe(true);
  expect((await forgot.json()).face_enrolled).toBe(false);
});

// The TV's "On your phone" QR against the real API: a phone token minted by
// POST /games/{id}/phone-link opens /p/:id, and every API call it makes carries that token
// as X-Replay-Phone-Token (never X-Replay-Key). This API runs without a key, so the 401
// path is services/api's own tests; here it is the page against the real routes.
test("S-55 live phone page: a minted phone token drives clip, tag, review and search", async ({
  page,
}) => {
  test.setTimeout(90_000);
  expect(gameId).not.toBe("");
  const minted = await page.request.post(`${API}/games/${gameId}/phone-link`, {
    data: { job: "clip", t: 2 },
  });
  test.skip(
    minted.status() === 404 || minted.status() === 405,
    "POST /games/{id}/phone-link is not in services/api yet",
  );
  expect(minted.status()).toBe(200);
  const link: { token: string; url: string | null } = await minted.json();
  expect(link.token.length).toBeGreaterThan(20);
  if (link.url)
    expect(link.url).toContain(`/p/${gameId}?job=clip&t=2#k=${link.token}`);

  const sent: { url: string; token?: string; key?: string }[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (
      u.origin === API &&
      !u.pathname.startsWith("/media/") &&
      r.method() !== "OPTIONS"
    )
      sent.push({
        url: `${r.method()} ${u.pathname}`,
        token: r.headers()["x-replay-phone-token"],
        key: r.headers()["x-replay-key"],
      });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/p/${gameId}?job=clip&t=2#k=${link.token}`);
  await expect(page.getByTestId("phone-title")).toHaveText("Live run");
  expect(new URL(page.url()).hash).toBe("");

  await expect(page.getByTestId("clip-video")).toHaveAttribute(
    "src",
    /\/media\/games\//,
  );
  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-note")).toHaveText(
    /^(Clip saved\.|No play ends here)/,
  );

  await page.getByTestId("phone-tab-tag").click();
  await expect(page.getByTestId("tag-player").first()).toBeVisible();

  await page.getByTestId("phone-tab-review").click();
  await expect(
    page
      .getByTestId("review-card")
      .first()
      .or(page.getByTestId("review-empty")),
  ).toBeVisible();

  await page.getByTestId("phone-tab-search").click();
  await page.getByTestId("phone-search-input").fill("shot");
  await page.getByTestId("phone-search-go").click();
  await expect(page.getByTestId("phone-search-interpretation")).toBeVisible();

  expect(sent.length).toBeGreaterThanOrEqual(6);
  for (const s of sent) {
    expect(s.token, s.url).toBe(link.token);
    expect(s.key, s.url).toBeUndefined();
  }
});
