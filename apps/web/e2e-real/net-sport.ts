// Shared body of R-04 (pickleball) and R-05 (badminton): the same Tier 1 walk through
// the product on a real net-sport clip. The two specs differ only by clip, sport and
// landmark file, so the walk lives here once (§4.9 rule: never branch on sport name).
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { API, SHOTS, clip, haveClip, shot, transform, videoState, waitForVideo } from "./helpers";

export interface NetSport {
  sport: "pickleball" | "badminton";
  variant: string;
  clip: string;
  landmarksFile: string;
  title: string;
  /** Stages the status page shows for a real courtcam run. */
  stages?: string[];
}

const STAGES = ["ingest", "detect", "track", "court", "identity", "crops", "events"];

interface Profile {
  id: string;
  sport_ui: { chips: string[]; review: string[]; court: { size_m: [number, number]; x_range: [number, number]; y_range: [number, number] } };
}

export async function profileOf(page: Page, sport: string): Promise<Profile> {
  const sports = await (await page.request.get(`${API}/sports`)).json();
  const hit = sports.find((s: Profile) => s.id === sport);
  expect(hit, `${sport} must be in GET /sports`).toBeTruthy();
  return hit;
}

/** Upload → calibrate → process. Returns the game id.
 *
 *  Calibration is POSTed rather than clicked: R-01 already proves the click walk on the
 *  calibrate screen, and these two specs are paying for real YOLO on two more clips. */
async function ingest(page: Page, s: NetSport): Promise<string> {
  await page.goto("/upload");
  await expect(page.getByTestId(`sport-option-${s.sport}`)).toBeVisible();
  await page.getByTestId("game-title-input").fill(s.title);
  await page.getByTestId(`sport-option-${s.sport}`).check();
  await page.getByTestId("create-game").click();
  await page.waitForURL(/\/upload\/g_[a-z0-9]+/);
  const gameId = new URL(page.url()).pathname.split("/")[2];

  await page.getByTestId("file-input").setInputFiles(clip(s.clip));
  await expect(page.getByTestId("upload-done")).toBeVisible({ timeout: 300_000 });

  const marks = JSON.parse(fs.readFileSync(clip(s.landmarksFile), "utf8"));
  const res = await page.request.post(`${API}/games/${gameId}/calibration`, {
    data: { sport: s.sport, variant: s.variant, landmarks_px: marks.landmarks_px },
  });
  expect(res.status(), await res.text()).toBe(200);
  const px = (await res.json()).reprojection_error_px;
  expect(px, "reprojection error on real net-sport footage").toBeLessThan(26);

  // Start processing over the API too: the calibrate screen only enables its button
  // once *its own* clicks have produced a calibration, and this spec deliberately
  // skipped those (R-01 proves them).
  const started = await page.request.post(`${API}/games/${gameId}/process`);
  expect(started.status(), await started.text()).toBe(202);
  await page.goto(`/upload/${gameId}/status`);
  for (const stage of s.stages ?? STAGES) {
    const row = page.getByTestId(`stage-${stage}`);
    if (await row.count()) {
      await expect(row).toHaveAttribute("data-state", /done|partial/, { timeout: 1_200_000 });
    }
  }
  await expect(page.getByTestId("game-status")).toHaveText("ready", { timeout: 300_000 });
  return gameId;
}

export function netSportSpec(s: NetSport) {
  test.describe.configure({ mode: "serial" });
  test.skip(!haveClip(s.clip), `samples/real/${s.clip} is gitignored (D-7); nothing to run`);
  test.skip(
    !haveClip(s.landmarksFile),
    `samples/real/${s.landmarksFile} is missing; calibrate the clip first`,
  );

  test(`${s.sport}: upload -> calibrate -> process -> select -> follow -> highlights -> review`, async ({
    page,
  }) => {
    test.setTimeout(1_800_000);
    const profile = await profileOf(page, s.sport);
    const gameId = await ingest(page, s);

    // --- select mode ------------------------------------------------------
    await page.goto(`/tv/${gameId}`);
    await waitForVideo(page);
    await page.keyboard.press("Space");
    await expect.poll(async () => (await videoState(page))?.paused).toBe(false);
    await expect.poll(async () => (await videoState(page))?.currentTime ?? 0).toBeGreaterThan(2);
    await page.keyboard.press("Space");
    await expect.poll(async () => (await videoState(page))?.paused).toBe(true);

    const boxes = page.locator('[data-testid^="select-box-"]');
    await expect(boxes.first()).toBeVisible({ timeout: 30_000 });
    // counted here, not in the summary below: by then we are on the review page.
    const selectBoxes = await boxes.count();
    expect(
      selectBoxes,
      "a doubles rally has four players; two selectable is the floor",
    ).toBeGreaterThanOrEqual(2);
    // W5: the court inset is drawn from the profile, so it exists for a net sport too.
    await expect(page.getByTestId("court-inset")).toBeVisible();
    await shot(page, `${s.sport}-select`);

    // --- follow mode ------------------------------------------------------
    const tBefore = (await videoState(page))!.currentTime;
    const wide = await transform(page);
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("followcam-active")).toBeVisible();
    await expect.poll(() => transform(page)).not.toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
    // W4: following is not a seek.
    expect(Math.abs((await videoState(page))!.currentTime - tBefore)).toBeLessThan(1 / 30 + 1e-6);
    await shot(page, `${s.sport}-follow`);

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("followcam-active")).toHaveCount(0);
    await expect.poll(() => transform(page)).toBe(wide);

    // --- highlights: the chips are this profile's, and each one resolves ---
    await page.goto(`/tv/${gameId}/highlights`);
    const chips = page.getByTestId("query-chip");
    await expect(chips.first()).toBeVisible();
    const labels = await chips.evaluateAll((els) =>
      els.map((e) => e.getAttribute("data-chip") ?? ""),
    );
    for (const chip of profile.sport_ui.chips) {
      expect(labels, `sport_ui.chips must reach the TV`).toContain(chip);
    }
    const target = labels.indexOf(profile.sport_ui.chips[0]);
    for (let i = 0; i < target; i++) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    // Tier 1: the rally detector is a stub, so the honest result is an interpretation
    // with no clips — not a dead button.
    await expect(page.getByTestId("query-interpretation")).toBeVisible();
    await expect(page.getByTestId("query-interpretation")).not.toHaveText(/No match/);
    await shot(page, `${s.sport}-highlights`);

    // --- review: the heatmap is drawn over THIS court ----------------------
    await page.goto(`/tv/${gameId}/review`);
    const heatmap = page.getByTestId("heatmap");
    await expect(heatmap).toBeVisible({ timeout: 30_000 });
    const [w, h] = profile.sport_ui.court.size_m;
    const want = `${profile.sport_ui.court.x_range[0]} ${profile.sport_ui.court.y_range[0]} ${w} ${h}`;
    expect(await heatmap.getAttribute("viewBox"), "heatmap drawn on the profile's court").toBe(
      want,
    );
    expect(await page.getByTestId("heatmap-cell").count(), "occupied heatmap cells").toBeGreaterThan(
      0,
    );
    await shot(page, `${s.sport}-review`);

    fs.mkdirSync(SHOTS, { recursive: true });
    const game = await (await page.request.get(`${API}/games/${gameId}`)).json();
    fs.writeFileSync(
      path.join(SHOTS, `${s.sport}-summary.json`),
      JSON.stringify(
        {
          gameId,
          sport: s.sport,
          variant: s.variant,
          players: game.players,
          teams: game.teams,
          duration_s: game.video?.duration_s,
          select_boxes: selectBoxes,
          chips: labels,
          heatmap_viewbox: want,
        },
        null,
        1,
      ),
    );
  });
}
