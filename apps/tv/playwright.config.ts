import { defineConfig, devices } from "@playwright/test";

// Projects:
//  tv        — the react-native-web build of apps/tv against the shared mock API
//              (packages/tv-core/src/mock.ts, same fixture games as apps/web's chromium project).
//  evidence  — opt-in (REPLAY_TV_API=<base of a running services/api>): walks a processed
//              game library → watch → select → follow and writes screenshots to
//              REPLAY_TV_EVIDENCE_DIR. Used for docs/evidence/M3 (synthetic sample) and
//              docs/evidence/local/M3 (real footage, gitignored).
// 1080p throughout: the 10-foot UI is designed and asserted at 1920x1080.
const VIEWPORT = { viewport: { width: 1920, height: 1080 } };
const PORT = 5181;
const EVIDENCE_PORT = 5182;
const API = process.env.REPLAY_TV_API;

export default defineConfig({
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  reporter: [["list"]],
  use: { trace: "retain-on-failure", ...VIEWPORT },
  projects: [
    {
      name: "tv",
      testDir: "./e2e",
      use: { ...devices["Desktop Chrome"], ...VIEWPORT, baseURL: `http://localhost:${PORT}` },
    },
    ...(API
      ? [
          {
            name: "evidence",
            testDir: "./e2e-evidence",
            fullyParallel: false,
            use: {
              ...devices["Desktop Chrome"],
              ...VIEWPORT,
              baseURL: `http://localhost:${EVIDENCE_PORT}`,
            },
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: `pnpm exec vite --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
      env: { VITE_MOCK_API: "1" },
    },
    ...(API
      ? [
          {
            command: `pnpm exec vite --port ${EVIDENCE_PORT} --strictPort`,
            url: `http://localhost:${EVIDENCE_PORT}/`,
            reuseExistingServer: false,
            timeout: 90_000,
            // REPLAY_TV_API=mock screenshots the mock fixture instead (a quick visual check).
            env:
              API === "mock"
                ? { VITE_MOCK_API: "1" }
                : { VITE_MOCK_API: "", VITE_REPLAY_API_BASE: API },
          },
        ]
      : []),
  ],
});
