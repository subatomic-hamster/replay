// TV-17 Free view (2.5D) in the player's angle view (docs/scene-format.md, D-75): Down enters
// the live scene of the play's package at the angle's media time, the D-pad orbits inside
// the envelope (hard clamps, edge bars), Rew/FF (`,` `.`) cycle presets, Menu (`m`)
// switches Up/Down to zoom, Select plays/pauses, Back returns to the video angle at the
// scene's time. The mock serves the committed SYNTHETIC fixture
// (services/api/fixtures/scene_synth) for play_0001.
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import type { SceneLayout, Vec3 } from "../../../packages/tv-core/src/types";
import {
  cameraPose,
  clampToEnvelope,
  easeCamera,
  envelopeEdges,
  MIN_STEP_MS,
  presetState,
  stepCamera,
  viewProjection,
} from "../src/scene/camera";
import { GAME_ID } from "./helpers";

const REPLAY = `/tv/${GAME_ID}/replays/play_0001`;

// REPLAY_SCENE_GPU=1: WebGL on the box's GPU (Vulkan) instead of SwiftShader, for the
// opt-in fps samples below (take the GPU lock). Default runs never set it.
if (process.env.REPLAY_SCENE_GPU) {
  test.use({
    launchOptions: {
      args: ["--use-angle=vulkan", "--ignore-gpu-blocklist", "--enable-gpu"],
    },
  });
}

function fixture(): SceneLayout {
  const file = path.resolve(
    test.info().project.testDir,
    "../../../services/api/fixtures/scene_synth/layout.json",
  );
  return JSON.parse(fs.readFileSync(file, "utf8")) as SceneLayout;
}

test("TV-17 camera: the real preset is the real camera; clamps, steps, easing", () => {
  const lay = fixture();
  const real = presetState("real", lay);
  const { R, eye } = cameraPose(real, lay);
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++)
      expect(Math.abs(R[i][j] - lay.camera.R[i][j])).toBeLessThan(1e-3);
    expect(Math.abs(eye[i] - lay.camera.position_m[i])).toBeLessThan(0.01);
  }
  // Same pixels as K·(R·X + t) for court points, through the GL matrix.
  const [w, h] = lay.camera.image_size;
  const vp = viewProjection(real, lay, w, h);
  expect(Math.abs(vp.f - lay.camera.K[0][0])).toBeLessThan(0.05);
  for (const X of [
    [0, 14, 0],
    [3, 5, 0],
    [-4, 20, 2],
  ] as Vec3[]) {
    const c = lay.camera.R.map(
      (r, k) => r[0] * X[0] + r[1] * X[1] + r[2] * X[2] + lay.camera.t[k],
    );
    const want = [
      (lay.camera.K[0][0] * c[0]) / c[2] + lay.camera.K[0][2],
      (lay.camera.K[1][1] * c[1]) / c[2] + lay.camera.K[1][2],
    ];
    const m = vp.matrix;
    const clip = [0, 1, 3].map(
      (r) => m[r] * X[0] + m[4 + r] * X[1] + m[8 + r] * X[2] + m[12 + r],
    );
    // GL window coordinates → OpenCV pixels (centres on integers)
    const got = [
      ((clip[0] / clip[2] + 1) / 2) * w - 0.5,
      ((1 - clip[1] / clip[2]) / 2) * h - 0.5,
    ];
    expect(Math.hypot(got[0] - want[0], got[1] - want[1])).toBeLessThan(0.5);
  }

  // Steps: 2.5° per press, hard clamp at the envelope, repeats faster than the hold rate dropped.
  const env = lay.envelope;
  let s = real;
  s = stepCamera(s, "left", Infinity, lay);
  expect(s.azimuth).toBeCloseTo(real.azimuth - 2.5, 6);
  expect(stepCamera(s, "left", MIN_STEP_MS / 2, lay)).toBe(s);
  for (let i = 0; i < 40; i++) s = stepCamera(s, "left", Infinity, lay);
  expect(s.azimuth).toBe(env.azimuth_deg[0]);
  // (the fixture's real camera is already the farthest allowed: d-max)
  const dEdge = envelopeEdges(real, lay).filter((x) => x.startsWith("d-"));
  expect(envelopeEdges(s, lay)).toEqual(["az-min", ...dEdge]);
  for (let i = 0; i < 40; i++) s = stepCamera(s, "up", Infinity, lay);
  expect(s.elevation).toBe(env.elevation_deg[1]);
  expect(envelopeEdges(s, lay)).toEqual(["az-min", "el-max", ...dEdge]);
  for (let i = 0; i < 40; i++) s = stepCamera(s, "zoom-in", Infinity, lay);
  expect(s.distance).toBe(env.distance_m[0]);
  expect(stepCamera(s, "reset", Infinity, lay)).toEqual(real);
  const wild = clampToEnvelope(
    { ...real, azimuth: 180, elevation: -90, distance: 1e3 },
    lay,
  );
  expect([wild.azimuth, wild.elevation, wild.distance]).toEqual([
    env.azimuth_deg[1],
    env.elevation_deg[0],
    env.distance_m[1],
  ]);

  // Easing: one time constant covers 1 − 1/e of the way, then it lands exactly.
  const hi = presetState("broadcast_high", lay);
  const one = easeCamera(real, hi, 140);
  expect(
    (one.elevation - real.elevation) / (hi.elevation - real.elevation),
  ).toBeCloseTo(1 - Math.exp(-1), 3);
  let e = real;
  for (let i = 0; i < 120; i++) e = easeCamera(e, hi, 16);
  expect(e).toEqual(hi);
});

const replayAttr = (page: Page, name: string) =>
  page.getByTestId("replay").getAttribute(`data-${name}`);
const viewAttr = (page: Page, name: string) =>
  page.getByTestId("free-view").getAttribute(`data-${name}`);

async function angleVideo(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? { t: v.currentTime, paused: v.paused, ready: v.readyState }
      : { t: -1, paused: true, ready: 0 };
  });
}

/** Open the replay paused at `t` (s), then enter Free view and wait for the first frame. */
async function enterFree(page: Page, t = 0.45) {
  await page.goto(REPLAY);
  await expect
    .poll(async () => (await angleVideo(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("replay")).toHaveAttribute("data-free", "true");
  await page.keyboard.press("Enter"); // pause the autoplaying angle
  await expect.poll(async () => (await angleVideo(page)).paused).toBe(true);
  await page.evaluate((to) => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    if (v) v.currentTime = to;
  }, t);
  await expect
    .poll(async () => Math.abs((await angleVideo(page)).t - t))
    .toBeLessThan(0.01);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("replay")).toHaveAttribute("data-mode", "free");
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-frame",
    String(Math.floor(t * 30)),
  );
}

async function press(page: Page, key: string) {
  await page.keyboard.press(key);
  await page.waitForTimeout(MIN_STEP_MS + 10);
}

/** Press `key` until the envelope edge `edge` is reported, at most `max` times. */
async function pushTo(page: Page, key: string, edge: string, max = 30) {
  for (let i = 0; i < max; i++) {
    if ((await replayAttr(page, "edges"))?.split(" ").includes(edge)) return i;
    await press(page, key);
  }
  throw new Error(`${edge} not reached with ${key}`);
}

test("TV-17 Free view: enter at the angle's time, clamp at every edge, presets, play/pause, Back", async ({
  page,
}) => {
  // ~28 s alone, so the default 30 s ran out with 4 workers (box-test runs the suite in parallel).
  test.slow();
  const lay = fixture();
  const env = lay.envelope;
  await enterFree(page);
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-settled",
    "true",
  );
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-preset",
    "real",
  );
  await expect(page.getByTestId("free-preset-label")).toHaveText("Real camera");
  await expect(page.getByTestId("replay-tier-badge")).toHaveText("2.5D");
  // The package's own honesty label (contract), plus the view-limit sentence (D-54).
  await expect(page.getByTestId("free-honesty")).toHaveText(lay.honesty_label);
  await expect(page.getByTestId("free-limit")).toHaveText(
    "View limited to what the camera saw",
  );
  await expect(page.getByTestId("replay-synthetic")).toBeVisible();
  await expect(page.getByTestId("free-gauge")).toBeVisible();
  for (const id of ["az-min", "az-max", "el-min", "el-max"])
    await expect(page.getByTestId(`edge-${id}`)).toHaveCount(0);

  // Orbit to each envelope edge: the state stops exactly on the limit, the bar shows.
  await pushTo(page, "ArrowLeft", "az-min");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-az",
    env.azimuth_deg[0].toFixed(2),
  );
  await expect(page.getByTestId("edge-az-min")).toBeVisible();
  await expect(page.getByTestId("free-preset-label")).toHaveText("Free camera");
  await press(page, "ArrowLeft"); // pushing further does nothing
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-az",
    env.azimuth_deg[0].toFixed(2),
  );
  await pushTo(page, "ArrowRight", "az-max");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-az",
    env.azimuth_deg[1].toFixed(2),
  );
  await expect(page.getByTestId("edge-az-max")).toBeVisible();
  await expect(page.getByTestId("edge-az-min")).toHaveCount(0);
  await pushTo(page, "ArrowUp", "el-max");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-el",
    env.elevation_deg[1].toFixed(2),
  );
  await expect(page.getByTestId("edge-el-max")).toBeVisible();
  await pushTo(page, "ArrowDown", "el-min");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-el",
    env.elevation_deg[0].toFixed(2),
  );
  await expect(page.getByTestId("edge-el-min")).toBeVisible();
  // Menu: Up/Down dolly instead.
  await page.keyboard.press("m");
  await expect(page.getByTestId("replay")).toHaveAttribute("data-zoom", "true");
  await pushTo(page, "ArrowUp", "d-min");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-dist",
    env.distance_m[0].toFixed(3),
  );
  await expect(page.getByTestId("free-gauge")).toContainText("closest");
  await pushTo(page, "ArrowDown", "d-max");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-dist",
    env.distance_m[1].toFixed(3),
  );
  await page.keyboard.press("m");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-zoom",
    "false",
  );

  // Presets: from a free camera FF goes to the first preset (real), then cycles through
  // every preset and wraps; Rew goes back.
  for (const p of [lay.presets[0], ...lay.presets.slice(1), lay.presets[0]]) {
    await page.keyboard.press(".");
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-preset",
      p.id,
    );
    await expect(page.getByTestId("free-preset-label")).toHaveText(p.label);
    const want = presetState(p.id, lay);
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-az",
      want.azimuth.toFixed(2),
    );
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-el",
      want.elevation.toFixed(2),
    );
  }
  await page.keyboard.press(",");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-preset",
    lay.presets[lay.presets.length - 1].id,
  );
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-settled",
    "true",
  );

  // Select plays the scene (the atlas advances), Select pauses it.
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-paused",
    "false",
  );
  await expect
    .poll(async () => Number(await viewAttr(page, "frame")), { timeout: 5_000 })
    .not.toBe(13);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-paused",
    "true",
  );
  const t1 = Number(await viewAttr(page, "time"));
  await page.waitForTimeout(400);
  const tScene = Number(await viewAttr(page, "time"));
  expect(tScene).toBeCloseTo(t1, 2);

  // Back: the video angle again, at the scene's time, still paused; Back again → the game.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-mode",
    "angles",
  );
  await expect(page.getByTestId("free-view")).toHaveCount(0);
  await expect
    .poll(async () => Math.abs((await angleVideo(page)).t - tScene))
    .toBeLessThan(0.05);
  expect((await angleVideo(page)).paused).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});

test("TV-17 Free view keeps text ≥ 24 px; a replay without a scene has no Free view", async ({
  page,
}) => {
  await enterFree(page);
  const small = await page.evaluate(() =>
    [...document.querySelectorAll("div, span")]
      .filter((el) =>
        [...el.childNodes].some(
          (n) => n.nodeType === 3 && n.textContent?.trim(),
        ),
      )
      .map((el) => ({
        text: el.textContent,
        size: parseFloat(getComputedStyle(el).fontSize),
      }))
      .filter((x) => x.size < 24),
  );
  expect(small).toEqual([]);

  await page.goto(`/tv/${GAME_ID}/replays/play_0002`);
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-mode",
    "angles",
  );
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-free",
    "false",
  );
  await expect(page.getByText("Free view", { exact: true })).toHaveCount(0);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-mode",
    "angles",
  );
});

// Opt-in (REPLAY_SCENE_SHOTS=<dir>): the bare canvas (overlays hidden) of every preset at
// frames 13 and 33 for the comparison with the reference renderer, plus an fps sample
// while the camera glides between presets and the atlas plays (fps.json). Headless
// Chromium renders WebGL with SwiftShader on the CPU: the fps is indicative only.
test("TV-17 reference shots and fps", async ({ page }) => {
  const dir = process.env.REPLAY_SCENE_SHOTS ?? "";
  test.skip(!dir, "set REPLAY_SCENE_SHOTS to write the comparison shots");
  test.setTimeout(120_000);
  const lay = fixture();
  fs.mkdirSync(dir, { recursive: true });
  for (const f of [13, 33]) {
    await enterFree(page, (f + 0.5) / lay.fps);
    await page.addStyleTag({
      content:
        '[data-testid="free-view"] ~ * { visibility: hidden !important; }',
    });
    for (const p of lay.presets) {
      while ((await replayAttr(page, "preset")) !== p.id)
        await page.keyboard.press(".");
      await expect(page.getByTestId("free-view")).toHaveAttribute(
        "data-settled",
        "true",
      );
      await page.waitForTimeout(150);
      await page.getByTestId("scene-canvas").screenshot({
        path: `${dir}/web_f${String(f).padStart(3, "0")}_${p.id}.png`,
      });
    }
  }
  // fps: play, and keep the camera moving for 8 s (a preset change every 400 ms).
  await page.keyboard.press("Enter");
  fs.writeFileSync(
    `${dir}/fps.json`,
    JSON.stringify(await sampleFps(page, 8000), null, 1),
  );
});

/** fps samples while playing and gliding between presets for `ms`, plus the GL renderer. */
async function sampleFps(page: Page, ms: number) {
  const fps: number[] = [];
  const drawMs: number[] = [];
  for (let i = 0; i * 400 < ms; i++) {
    await page.keyboard.press(i % 2 ? "," : ".");
    await page.waitForTimeout(400);
    if (i % 3 === 2) {
      fps.push(Number(await viewAttr(page, "fps")));
      drawMs.push(Number(await viewAttr(page, "draw-ms")));
    }
  }
  const renderer = await page.evaluate(() => {
    const gl = document
      .querySelector<HTMLCanvasElement>('[data-testid="scene-canvas"]')
      ?.getContext("webgl2");
    const d = gl?.getExtension("WEBGL_debug_renderer_info");
    return d && gl ? String(gl.getParameter(d.UNMASKED_RENDERER_WEBGL)) : null;
  });
  return { fps, drawMs, renderer };
}

// Opt-in live run on REAL packages (LOCAL ONLY, D-7): REPLAY_SCENE_LIVE = the TV web build
// served against an API whose data has the packages, REPLAY_SCENE_LIVE_PLAYS =
// "g_kenn/pl_0001,…", REPLAY_SCENE_LIVE_SHOTS = an output dir under docs/evidence/local.
// Per play: the presets, the two clamped azimuth edges and the top edge (with the
// overlays), and an fps sample.
test("TV-17 live: real scene packages", async ({ page }) => {
  const base = process.env.REPLAY_SCENE_LIVE ?? "";
  const dir = process.env.REPLAY_SCENE_LIVE_SHOTS ?? "";
  test.skip(
    !base || !dir,
    "set REPLAY_SCENE_LIVE, REPLAY_SCENE_LIVE_PLAYS and REPLAY_SCENE_LIVE_SHOTS",
  );
  test.setTimeout(300_000);
  fs.mkdirSync(dir, { recursive: true });
  const report: Record<string, unknown> = {};
  for (const spec of (process.env.REPLAY_SCENE_LIVE_PLAYS ?? "")
    .split(",")
    .filter(Boolean)) {
    const [game, play] = spec.split("/");
    const name = `${game}_${play}`;
    await page.goto(`${base}/tv/${game}/replays/${play}`);
    await expect
      .poll(async () => (await angleVideo(page)).ready, { timeout: 30_000 })
      .toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-free",
      "true",
      { timeout: 15_000 },
    );
    await expect
      .poll(async () => (await angleVideo(page)).t, { timeout: 10_000 })
      .toBeGreaterThan(1.5);
    await page.keyboard.press("Enter"); // pause the autoplaying angle ~1/4 into the play
    await expect.poll(async () => (await angleVideo(page)).paused).toBe(true);
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("free-view")).toHaveAttribute(
      "data-ready",
      "true",
      { timeout: 30_000 },
    );
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-paused",
      "true",
    );
    const presets: string[] = [];
    for (let i = 0; i < 5; i++) {
      const id = (await replayAttr(page, "preset")) ?? "";
      await expect(page.getByTestId("free-view")).toHaveAttribute(
        "data-settled",
        "true",
      );
      await page.waitForTimeout(200);
      await page.screenshot({ path: `${dir}/${name}_preset_${id}.png` });
      presets.push(id);
      await page.keyboard.press(".");
    }
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-preset",
      "real",
    );
    const edges: Record<string, Record<string, string | null>> = {};
    for (const [key, edge] of [
      ["ArrowLeft", "az-min"],
      ["ArrowRight", "az-max"],
      ["ArrowUp", "el-max"],
    ] as const) {
      const presses = await pushTo(page, key, edge);
      await expect(page.getByTestId(`edge-${edge}`)).toBeVisible();
      await expect(page.getByTestId("free-view")).toHaveAttribute(
        "data-settled",
        "true",
      );
      await page.waitForTimeout(200);
      await page.screenshot({ path: `${dir}/${name}_edge_${edge}.png` });
      edges[edge] = {
        presses: String(presses),
        az: await replayAttr(page, "az"),
        el: await replayAttr(page, "el"),
        dist: await replayAttr(page, "dist"),
      };
    }
    await page.keyboard.press("Enter"); // play
    report[name] = { presets, edges, ...(await sampleFps(page, 6000)) };
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("replay")).toHaveAttribute(
      "data-mode",
      "angles",
    );
  }
  fs.writeFileSync(`${dir}/live.json`, JSON.stringify(report, null, 1));
});
