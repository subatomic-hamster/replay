// Shared bits for the opt-in `real` project: real footage, real courtcam, real YOLO.
// The clips live in samples/real/ and are gitignored (D-7), so every test here skips
// itself when its clip is missing rather than failing the suite.
import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(here, "../../..");
export const API = "http://localhost:8010";
export const SHOTS = process.env.REPLAY_E2E_SHOTS ?? path.join(os.tmpdir(), "replay-real-shots");

export const clip = (name: string) => path.join(REPO, "samples/real", name);
export const haveClip = (name: string) => fs.existsSync(clip(name));

/** `basketball_kennesawwide_240s.landmarks.json`, in 2560x960 source pixels. The smoke
 *  cut has the same framing, so the same clicks calibrate both. `corner_fr` is off the
 *  bottom of the frame on this camera and is deliberately absent — see R-01. */
export function landmarks(): Record<string, [number, number]> {
  const file = clip("basketball_kennesawwide_240s.landmarks.json");
  return JSON.parse(fs.readFileSync(file, "utf8")).landmarks_px;
}

export async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

export async function videoState(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v && { currentTime: v.currentTime, paused: v.paused, readyState: v.readyState };
  });
}

export async function waitForVideo(page: Page) {
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await videoState(page))?.readyState ?? 0, { timeout: 60_000 })
    .toBeGreaterThanOrEqual(2);
}

export async function transform(page: Page) {
  return page.evaluate(
    () => getComputedStyle(document.querySelector('[data-testid="player-transform"]')!).transform,
  );
}

/** The id of the newest ready game whose title matches, or "" if there is none. */
export async function findGame(page: Page, title: string): Promise<string> {
  const games = await (await page.request.get(`${API}/games`)).json();
  const hit = games.filter(
    (g: { title: string; status: string }) => g.title === title && g.status === "ready",
  );
  return hit.length ? hit[hit.length - 1].id : "";
}

/** Walk the calibrate screen: click every landmark we have a pixel for, skip the rest. */
export async function calibrate(page: Page, variant: "half" | "full", marks: Record<string, [number, number]>) {
  const img = page.getByTestId("calib-image");
  await expect(img).toBeVisible();
  await page.getByTestId(`variant-${variant}`).check();
  // The optional landmarks are the whole point on this footage: with corner_fr missing,
  // 3 corners + rim is 4 points and a degenerate fit; the key/ft/centre points are what
  // make it 0.26 px (samples/real/RESULTS.md).
  await page.getByTestId("calib-more").click();

  const frame = await img.evaluate((el: HTMLImageElement) => ({
    w: el.naturalWidth,
    h: el.naturalHeight,
  }));
  expect(frame.w, "D-14: the calibration frame exists before processing").toBeGreaterThan(0);
  const box = (await img.boundingBox())!;

  for (let guard = 0; guard < 40; guard++) {
    const prompt = await page.getByTestId("calib-prompt").textContent();
    const m = /^Tap ([a-z ]+?) — point/.exec(prompt?.trim() ?? "");
    if (!m) break; // "All landmarks placed."
    const name = m[1].trim().replace(/ /g, "_");
    const px = marks[name];
    if (!px) {
      await page.getByTestId("calib-skip").click();
      continue;
    }
    await page.mouse.click(
      box.x + (px[0] / frame.w) * box.width,
      box.y + (px[1] / frame.h) * box.height,
    );
    await expect(page.getByTestId(`landmark-${name}`)).toBeVisible();
  }

  const error = page.getByTestId("calib-error");
  await expect(error).toHaveAttribute("data-ok", "true", { timeout: 20_000 });
  return Number((await error.textContent())!.replace(" px", ""));
}
