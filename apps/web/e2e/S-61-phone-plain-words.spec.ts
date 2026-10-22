// S-61: phone pages follow-up to the UI pass, at 390x844 against the mock API. Plain words
// on the processing page and the sport picker, profile rows that are one link each with an
// honest game count, an expired link that says how to get a new one, and nothing on the
// Clip tab hidden under the fixed tab bar.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID } from "./helpers";

const PHONE = { width: 390, height: 844 };
test.use({ viewport: PHONE, hasTouch: true });

/** PHONE_FIX_SHOTS=<dir> writes the review screenshots. */
async function shot(page: Page, name: string, fullPage = true) {
  const dir = process.env.PHONE_FIX_SHOTS;
  if (dir) await page.screenshot({ path: `${dir}/${name}.png`, fullPage });
}

test("S-61 processing status reads in plain words; stage keys stay in the test ids", async ({
  page,
}) => {
  await page.goto("/upload/g_proc03/status"); // seeded mid-run, `detect` running
  await expect(page.getByTestId("game-status")).toHaveText("Processing");
  const names = page.locator(".stage-name");
  await expect(names).toHaveText([
    "Preparing the video",
    "Fitting the court",
    "Finding players",
    "Following players",
    "Mapping the court",
    "Telling players apart",
    "Saving each player's path",
    "Framing each player",
    "Spotting plays",
  ]);
  // Honest about what is done and what is not: the mock moves one stage per poll, so read
  // every row's state and words in one go and check each matches its own state.
  const WORDS: Record<string, RegExp> = {
    done: /^Done$/,
    running: /^Working · \d+%$/,
    pending: /^Waiting$/,
  };
  const rows = await page
    .locator('[data-testid^="stage-"]')
    .evaluateAll((els) =>
      els.map((e) => ({
        state: e.getAttribute("data-state") ?? "",
        words: e.querySelector(".stage-state")?.textContent ?? "",
      })),
    );
  expect(rows.map((r) => r.state).join(",")).toMatch(
    /^(done,)*running(,pending)*$/,
  );
  for (const r of rows) expect(r.words).toMatch(WORDS[r.state]);
  await expect(page.locator(".stages")).not.toContainText(
    /pending|running|ingest|crops/,
  );
  await shot(page, "status");
});

test("S-61 the sport picker shows sport names, no tier", async ({ page }) => {
  await page.goto("/upload");
  await expect(page.locator("fieldset")).toContainText("Basketball");
  await expect(page.locator("fieldset")).not.toContainText(/tier/i);
  await shot(page, "new-game");
});

test("S-61 profiles: the whole row opens the profile, by tap or keyboard; game counts are honest", async ({
  page,
}) => {
  await page.goto("/profiles");
  const marcus = page.locator(
    '[data-testid="phone-profile"][data-profile-id="pr_00000000a001"]',
  );
  // Marcus has two linked games and no hand-set sports: never "No games linked yet".
  await expect(marcus.getByTestId("phone-profile-meta")).toHaveText("2 games");
  const sam = page.locator(
    '[data-testid="phone-profile"][data-profile-id="pr_00000000a003"]',
  );
  await expect(sam.getByTestId("phone-profile-meta")).toHaveText(
    "Pickleball · No games linked yet",
  );
  // a long summary wraps inside its row, not past the edge
  for (const row of await page.getByTestId("phone-profile").all()) {
    const r = (await row.boundingBox())!;
    const m = (await row.getByTestId("phone-profile-meta").boundingBox())!;
    expect(m.x + m.width).toBeLessThanOrEqual(r.x + r.width);
  }
  await shot(page, "profiles");

  // One link per row, named by the person.
  await expect(marcus.getByRole("link")).toHaveCount(1);
  await expect(marcus.getByRole("link")).toContainText("Marcus");
  // A tap on the far right of the row (the meta text, not the name) opens it.
  const box = (await marcus.boundingBox())!;
  await page.mouse.click(box.x + box.width - 12, box.y + box.height / 2);
  await expect(page).toHaveURL(/\/profiles\/pr_00000000a001$/);

  await page.goBack();
  await expect(page.getByTestId("phone-profiles")).toBeVisible();
  await sam.getByRole("link").focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/profiles\/pr_00000000a003$/);
});

test("S-61 an expired phone link says how to get a new one", async ({
  page,
}) => {
  await page.goto(`/p/${GAME_ID}?job=clip#k=expired`);
  await expect(page.getByTestId("qr-problem")).toContainText("expired");
  await expect(
    page.getByRole("heading", { name: "Get a new link" }),
  ).toBeVisible();
  await expect(page.getByTestId("qr-next-steps").locator("li")).toHaveCount(3);
  await shot(page, "expired-phone-link");

  await page.goto("/u/g_qr05#t=expired");
  await page.reload(); // a hash-only change does not reload
  await expect(page.getByTestId("qr-next-steps")).toContainText("Add game");
  await shot(page, "expired-upload-link");
});

test("S-61 Clip: Save clip and the share link clear the fixed tab bar", async ({
  page,
}) => {
  await page.goto(`/p/${GAME_ID}?job=clip&t=17.2#k=tok_phone`);
  await expect(page.getByTestId("clip-save")).toBeVisible();
  const clear = async (testId: string) => {
    await page.evaluate(() =>
      window.scrollTo(0, document.documentElement.scrollHeight),
    );
    return page.evaluate((id) => {
      const el = document
        .querySelector(`[data-testid="${id}"]`)!
        .getBoundingClientRect();
      const bar = document
        .querySelector(".phone-tabs")!
        .getBoundingClientRect();
      return el.bottom <= bar.top;
    }, testId);
  };
  expect(await clear("clip-save"), "Save clip above the tab bar").toBe(true);
  // the viewport as the thumb sees it, scrolled to the bottom, tab bar included
  await shot(page, "clip-bottom", false);

  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("clip-link")).toBeVisible();
  expect(await clear("clip-link"), "share link above the tab bar").toBe(true);
  await shot(page, "clip-saved-bottom", false);
});
