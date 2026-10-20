import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

// S-55..S-59: the "On your phone" page the TV's QR opens, `/p/:id?job=..&t=..#k=<token>`,
// at phone size against the mock API. The mock reads the token like the API does: any
// token opens the game, "expired" 401s every call.

const PHONE = { width: 390, height: 844 };
const TOKEN = "tok_phone";
const here = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.resolve(here, "../../../shots");

test.use({ viewport: PHONE, hasTouch: true });

const open = (page: Page, query: string) =>
  page.goto(`/p/${GAME_ID}?${query}#k=${TOKEN}`);

/** One hand, one screen wide: no sideways scroll, nothing under 16 px. */
async function phoneFriendly(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    "no horizontal scroll",
  ).toBe(true);
  const small = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("body *")]
      .filter(
        (el) =>
          el.offsetParent !== null &&
          [...el.childNodes].some(
            (n) => n.nodeType === 3 && n.textContent?.trim(),
          ),
      )
      .map((el) => ({
        text: el.textContent,
        size: parseFloat(getComputedStyle(el).fontSize),
      }))
      .filter((x) => x.size < 16),
  );
  expect(small, "text under 16 px").toEqual([]);
}

const calls = async (page: Page, method: string, prefix: string) =>
  (await mockCalls(page)).filter(
    (c) => c.method === method && c.path.startsWith(prefix),
  );

test("S-55 the token comes from the fragment, leaves the address bar and survives a reload", async ({
  page,
}) => {
  await open(page, "job=review&t=3");
  await expect(page.getByTestId("phone-title")).toHaveText(
    "Tuesday run — CRC court 2",
  );
  await expect(page.getByTestId("phone-tab-review")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByTestId("phone-review")).toBeVisible();
  expect(new URL(page.url()).hash).toBe(""); // stripped with history.replaceState
  expect(new URL(page.url()).search).toBe("?job=review&t=3");
  expect(
    await page.evaluate(
      (id) => sessionStorage.getItem(`replay.phone.${id}`),
      GAME_ID,
    ),
  ).toBe(TOKEN);

  await page.reload();
  await expect(page.getByTestId("phone-title")).toBeVisible();

  // The tabs switch jobs in place (no reload, the token stays) and the URL follows.
  await page.getByTestId("phone-tab-search").click();
  await expect(page.getByTestId("phone-search")).toBeVisible();
  await expect(page.getByTestId("phone-review")).toBeHidden();
  expect(new URL(page.url()).searchParams.get("job")).toBe("search");
  await page.getByTestId("phone-tab-tag").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("phone-tag")).toBeVisible();
  // Visible focus: the focused tab has an outline.
  expect(
    await page
      .getByTestId("phone-tab-tag")
      .evaluate((el) => getComputedStyle(el).outlineStyle),
  ).not.toBe("none");
});

test("S-55 an expired or missing code says to scan again", async ({ page }) => {
  await page.goto(`/p/${GAME_ID}?job=clip#k=expired`);
  await expect(page.getByTestId("qr-problem")).toHaveText(
    "This link has expired. Scan the code on the TV again.",
  );
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0);

  const fresh = await page.context().newPage(); // a new tab: no sessionStorage
  await fresh.goto(`/p/${GAME_ID}?job=clip`);
  await expect(fresh.getByTestId("qr-problem")).toContainText(
    "missing its code",
  );
});

test("S-56 Clip: the moment near t, trimmed, saved as a new clip through the tap route, 16:9 link", async ({
  page,
}) => {
  await open(page, "job=clip&t=17.2");
  // e_0004 (t 17, window 15.5–18.5) is the moment at t; no clip covers it yet.
  await expect(page.getByTestId("clip-moment")).toHaveValue("e_0004");
  await expect(page.getByTestId("clip-start")).toHaveText("0:15.5");
  await expect(page.getByTestId("clip-end")).toHaveText("0:18.5");
  await expect(page.getByTestId("clip-video")).toHaveAttribute(
    "src",
    /wide\.mp4/,
  );
  await phoneFriendly(page);

  await page.getByTestId("clip-start-later").click();
  await expect(page.getByTestId("clip-start")).toHaveText("0:16.0");
  await expect(page.getByTestId("clip-length")).toHaveText("2.5 s");

  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-note")).toHaveText("Clip saved.");
  const clipId = await page
    .getByTestId("clip-note")
    .getAttribute("data-clip-id");
  expect(clipId).toMatch(/^c_u\d+$/);
  expect(await calls(page, "POST", `/games/${GAME_ID}/triggers`)).toEqual([
    { method: "POST", path: `/games/${GAME_ID}/triggers`, body: { t: 18.5 } },
  ]);
  expect(await calls(page, "PATCH", `/games/${GAME_ID}/clips/`)).toEqual([
    {
      method: "PATCH",
      path: `/games/${GAME_ID}/clips/${clipId}`,
      body: { t_start: 16, t_end: 18.5 },
    },
  ]);
  await expect(page.getByTestId("clip-link")).toHaveText("Open clip");
  await expect(page.getByTestId("clip-link")).toHaveAttribute(
    "href",
    /wide\.mp4#t=16,18\.5$/,
  );

  // A second save edits the same clip; it does not cut another one.
  await page.getByTestId("clip-end-earlier").click();
  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-note")).toHaveText("Clip saved.");
  expect(await calls(page, "POST", `/games/${GAME_ID}/triggers`)).toHaveLength(
    1,
  );
  expect(
    (await calls(page, "PATCH", `/games/${GAME_ID}/clips/`)).at(-1)?.body,
  ).toEqual({
    t_start: 16,
    t_end: 18,
  });
  await phoneFriendly(page);
});

test("S-56 Clip 9:16: trims the clip already cut there, renders the vertical cut, download link", async ({
  page,
}) => {
  await open(page, "job=clip&t=3");
  await expect(page.getByTestId("clip-moment")).toHaveValue("e_0001"); // window 1.5–4.5
  await page.getByTestId("clip-aspect-tall").click();
  await expect(page.getByTestId("clip-aspect-tall")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-rendering")).toHaveText(
    "Rendering the 9:16 cut…",
  );
  await expect(page.getByTestId("clip-link")).toHaveText("Download 9:16 clip", {
    timeout: 10_000,
  });
  await expect(page.getByTestId("clip-link")).toHaveAttribute(
    "href",
    /export=v_/,
  );
  // c_g1 (0–5.5) already covers t = 3: trimmed, not a new tap.
  expect(await calls(page, "POST", `/games/${GAME_ID}/triggers`)).toEqual([]);
  expect(await calls(page, "PATCH", `/games/${GAME_ID}/clips/`)).toEqual([
    {
      method: "PATCH",
      path: `/games/${GAME_ID}/clips/c_g1`,
      body: { t_start: 1.5, t_end: 4.5 },
    },
  ]);
  expect(
    await calls(page, "POST", `/games/${GAME_ID}/exports/vertical`),
  ).toEqual([
    {
      method: "POST",
      path: `/games/${GAME_ID}/exports/vertical`,
      body: { clip_id: "c_g1" },
    },
  ]);
  await phoneFriendly(page);
});

test("S-57 Tag: players with thumbs; link one to a profile, name another as someone new", async ({
  page,
}) => {
  await open(page, "job=tag");
  const players = page.getByTestId("tag-player");
  await expect(players).toHaveCount(4);
  await expect(
    page.locator(
      '[data-testid="tag-player"][data-player-id="p2"] .player-thumb',
    ),
  ).toHaveAttribute("data-thumb", "true");
  await phoneFriendly(page);

  await page.locator('[data-testid="tag-player"][data-player-id="p2"]').click();
  await expect(page.getByTestId("tag-panel")).toBeVisible();
  await page
    .locator('[data-testid="tag-profile"][data-profile-id="pr_00000000a002"]')
    .click();
  await expect(page.getByTestId("tag-note")).toHaveText("Tagged as Jordan.");
  await expect(
    page.locator('[data-testid="tag-player"][data-player-id="p2"]'),
  ).toHaveAttribute("data-name", "Jordan");
  expect(await calls(page, "POST", "/profiles/pr_00000000a002/links")).toEqual([
    {
      method: "POST",
      path: "/profiles/pr_00000000a002/links",
      body: { game_id: GAME_ID, player_id: "p2" },
    },
  ]);

  await page.locator('[data-testid="tag-player"][data-player-id="p4"]').click();
  await page.getByTestId("tag-new-name").fill("Riley");
  await page.getByTestId("tag-new-save").click();
  await expect(page.getByTestId("tag-note")).toHaveText("Tagged as Riley.");
  await expect(
    page.locator('[data-testid="tag-player"][data-player-id="p4"]'),
  ).toHaveAttribute("data-name", "Riley");
  const made = await calls(page, "POST", "/profiles");
  expect(
    made.slice(1).map((c) => [c.path.replace(/pr_\w+/, "pr_new"), c.body]),
  ).toEqual([
    ["/profiles", { name: "Riley" }],
    ["/profiles/pr_new/links", { game_id: GAME_ID, player_id: "p4" }],
  ]);
});

test("S-58 Review: the queue as cards with the TV's answers, a typed name included", async ({
  page,
}) => {
  await open(page, "job=review");
  const cards = page.getByTestId("review-card");
  await expect(cards.first()).toBeVisible();
  const before = await cards.count();
  expect(before).toBeGreaterThanOrEqual(2);
  await phoneFriendly(page);

  const shot = page
    .locator('[data-testid="review-card"][data-kind="low_confidence"]')
    .first();
  await shot.getByTestId("review-action-yes").click();
  await expect(page.getByTestId("review-note")).toHaveText("Saved: Yes.");
  await expect(cards).toHaveCount(before - 1);
  expect(await calls(page, "PATCH", `/games/${GAME_ID}/events/`)).toEqual([
    {
      method: "PATCH",
      path: `/games/${GAME_ID}/events/e_0004`,
      body: { confirmed: true },
    },
  ]);

  const who = page
    .locator('[data-testid="review-card"][data-kind="identity"]')
    .first();
  await who.getByTestId("review-action-type-a-name").click();
  await page.getByTestId("review-text").fill("Sam");
  await page.getByTestId("review-text-save").click();
  await expect(page.getByTestId("review-note")).toHaveText("Saved: Sam.");
  await expect(cards).toHaveCount(before - 2);
  expect(await calls(page, "PATCH", `/games/${GAME_ID}/players/`)).toEqual([
    {
      method: "PATCH",
      path: `/games/${GAME_ID}/players/p2`,
      body: { name: "Sam" },
    },
  ]);
});

test("S-59 Search: this game's plays; a hit plays its window on the phone", async ({
  page,
}) => {
  await open(page, "job=search");
  await page.getByTestId("phone-search-input").fill("Marcus scores");
  await page.getByTestId("phone-search-go").click();
  const hits = page.getByTestId("phone-search-hit");
  await expect(hits.first()).toBeVisible();
  expect(await calls(page, "POST", `/games/${GAME_ID}/search`)).toEqual([
    {
      method: "POST",
      path: `/games/${GAME_ID}/search`,
      body: { text: "Marcus scores", k: 8 },
    },
  ]);
  await phoneFriendly(page);

  const second = hits.nth(1);
  const t0 = Number(await second.getAttribute("data-t-start"));
  await second.click();
  await expect(second).toHaveAttribute("aria-pressed", "true");
  const preview = page.getByTestId("phone-search-preview");
  await expect(preview).toHaveAttribute("data-t-start", String(t0));
  await expect
    .poll(() => preview.evaluate((v: HTMLVideoElement) => v.currentTime), {
      timeout: 10_000,
    })
    .toBeGreaterThanOrEqual(t0 - 0.05);

  // A chip searches in one tap.
  await page.getByTestId("phone-search-chip").first().click();
  await expect(page.getByTestId("phone-search-input")).not.toHaveValue(
    "Marcus scores",
  );
  await expect(page.getByTestId("phone-search-interpretation")).toBeVisible();
});

test("S-59 screenshots of the four tabs at 390x844", async ({ page }) => {
  test.skip(
    !process.env.PHONE_SHOTS,
    "PHONE_SHOTS=1 writes the review screenshots",
  );
  await open(page, "job=clip&t=17.2");
  await expect(page.getByTestId("clip-start")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p-clip.png` });
  await page.getByTestId("clip-aspect-tall").click();
  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-link")).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}/p-clip-916.png`, fullPage: true });
  await page.getByTestId("phone-tab-tag").click();
  await page.locator('[data-testid="tag-player"][data-player-id="p2"]').click();
  await page.screenshot({ path: `${SHOTS}/p-tag.png` });
  await page.getByTestId("phone-tab-review").click();
  await expect(page.getByTestId("review-card").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p-review.png` });
  await page.getByTestId("phone-tab-search").click();
  await page.getByTestId("phone-search-input").fill("Marcus");
  await page.getByTestId("phone-search-go").click();
  await page.getByTestId("phone-search-hit").first().click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/p-search.png` });
  await page.goto(`/p/${GAME_ID}?job=clip#k=expired`);
  await expect(page.getByTestId("qr-problem")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/p-expired.png` });
});
