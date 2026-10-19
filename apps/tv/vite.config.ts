// Web build of the RN TV app (react-native-web) — what Playwright drives and screenshots.
// `.web.*` files win over shared ones, mirroring how Metro picks `.native.*` / `.android.*`.
import { fileURLToPath } from "node:url";
import { defineConfig, searchForWorkspaceRoot, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const extensions = [".web.tsx", ".web.ts", ".web.js", ".tsx", ".ts", ".mjs", ".js", ".jsx", ".json"];

// The mock API's 2.5D scene (MOCK_SCENE_DIR in packages/tv-core/src/mock.ts) is the
// committed SYNTHETIC fixture of services/api, served in place through Vite's /@fs/ (Range
// requests included) instead of a copy under public/.
const SCENE_FIXTURE = fileURLToPath(new URL("../../services/api/fixtures/scene_synth", import.meta.url));
const mockScene: Plugin = {
  name: "mock-scene",
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url?.startsWith("/mock/scene_synth/")) {
        req.url = `/@fs${SCENE_FIXTURE}/${req.url.slice("/mock/scene_synth/".length)}`;
      }
      next();
    });
  },
};

export default defineConfig(({ mode }) => ({
  // D-80: the deployed TV web build sits under /tvapp/ next to apps/web at /.
  base: process.env.VITE_BASE || "/",
  plugins: [react(), mockScene],
  resolve: {
    alias: { "react-native": "react-native-web" },
    extensions,
  },
  define: {
    __DEV__: JSON.stringify(mode !== "production"),
  },
  optimizeDeps: { esbuildOptions: { resolveExtensions: extensions } },
  // The mock API's fixture media (wide.mp4, calib.jpg) — served, not copied.
  publicDir: "../web/public",
  server: {
    port: 5180,
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../../packages/tv-core", "../web/public", SCENE_FIXTURE] },
  },
}));
