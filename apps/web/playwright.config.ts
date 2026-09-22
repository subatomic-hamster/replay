import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(here, "../..");

const PORT = 5177; // mock-mode dev server
const LIVE_PORT = 5178; // dev server pointed at the real API
const API_PORT = 8000;
const API_BASE = `http://localhost:${API_PORT}`;
// Wiped by the uvicorn command below, so every run starts with an empty library.
const DATA_DIR = path.join(os.tmpdir(), "replay-e2e-data");

// 10-foot UI: everything is designed and asserted at 1080p. This has to be spread
// AFTER devices["Desktop Chrome"], which carries its own 1280x720 viewport and would
// otherwise silently override the top-level `use.viewport`.
const VIEWPORT = { viewport: { width: 1920, height: 1080 } };

// Opt-in `real` project: the REAL courtcam pipeline (YOLO on CPU) on real footage from
// samples/real/, which is gitignored (D-7) and takes minutes per clip. Off unless
// REPLAY_E2E_REAL=1, and its data dir is NOT wiped between runs so a processed game can
// be reused. `pnpm exec playwright test --project=real` with REPLAY_E2E_REAL=1.
const REAL = !!process.env.REPLAY_E2E_REAL;
const REAL_PORT = 5179;
const REAL_API_PORT = 8010;
const REAL_API_BASE = `http://localhost:${REAL_API_PORT}`;
const REAL_DATA_DIR =
  process.env.REPLAY_E2E_REAL_DATA ?? path.join(os.tmpdir(), "replay-e2e-real-data");

export default defineConfig({
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"]],
  use: {
    trace: "retain-on-failure",
    ...VIEWPORT,
  },
  projects: [
    {
      name: "chromium",
      testDir: "./e2e",
      use: { ...devices["Desktop Chrome"], ...VIEWPORT, baseURL: `http://localhost:${PORT}` },
    },
    {
      // The same screens against services/api in REPLAY_PIPELINE=fake mode. Serial:
      // one API process, one data dir, and the tests share the game they upload.
      name: "live",
      testDir: "./e2e-live",
      fullyParallel: false,
      use: { ...devices["Desktop Chrome"], ...VIEWPORT, baseURL: `http://localhost:${LIVE_PORT}` },
    },
    ...(REAL
      ? [
          {
            name: "real",
            testDir: "./e2e-real",
            fullyParallel: false,
            use: {
              ...devices["Desktop Chrome"],
              ...VIEWPORT,
              baseURL: `http://localhost:${REAL_PORT}`,
            },
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: `pnpm exec vite --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}/tv`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { VITE_MOCK_API: "1" },
    },
    {
      command: `rm -rf ${DATA_DIR} && uv run --package replay-api uvicorn replay_api.main:app --port ${API_PORT}`,
      cwd: REPO,
      url: `${API_BASE}/healthz`,
      // never reuse: the data dir is wiped by the command, so a stale process would
      // be serving games this run knows nothing about
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        REPLAY_PIPELINE: "fake",
        REPLAY_DATA_DIR: DATA_DIR,
        REPLAY_FAKE_PIPELINE_DIR: path.join(REPO, "services/api/fixtures/fake_game"),
        // S-08: fake mode finishes in seconds, so hold each stage long enough for the
        // status page's 2 s poll to catch a `running` one.
        REPLAY_FAKE_PIPELINE_DELAY_S: "1",
      },
    },
    {
      command: `pnpm exec vite --port ${LIVE_PORT} --strictPort`,
      url: `http://localhost:${LIVE_PORT}/tv`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { VITE_MOCK_API: "", VITE_REPLAY_API_BASE: API_BASE },
    },
    ...(REAL
      ? [
          {
            // REPLAY_PIPELINE is deliberately unset: this one runs courtcam for real.
            command: `uv run --package replay-api uvicorn replay_api.main:app --port ${REAL_API_PORT}`,
            cwd: REPO,
            url: `${REAL_API_BASE}/healthz`,
            reuseExistingServer: true,
            timeout: 120_000,
            env: { REPLAY_DATA_DIR: REAL_DATA_DIR },
          },
          {
            command: `pnpm exec vite --port ${REAL_PORT} --strictPort`,
            url: `http://localhost:${REAL_PORT}/tv`,
            reuseExistingServer: true,
            timeout: 60_000,
            env: { VITE_MOCK_API: "", VITE_REPLAY_API_BASE: REAL_API_BASE },
          },
        ]
      : []),
  ],
});
