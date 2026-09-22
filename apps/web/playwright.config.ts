import { defineConfig, devices } from "@playwright/test";

const PORT = 5177;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    // 10-foot UI: everything is designed and asserted at 1080p.
    viewport: { width: 1920, height: 1080 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/tv`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: { VITE_MOCK_API: "1" },
  },
});
