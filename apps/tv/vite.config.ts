// Web build of the RN TV app (react-native-web) — what Playwright drives and screenshots.
// `.web.*` files win over shared ones, mirroring how Metro picks `.native.*` / `.android.*`.
import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";

const extensions = [".web.tsx", ".web.ts", ".web.js", ".tsx", ".ts", ".mjs", ".js", ".jsx", ".json"];

export default defineConfig(({ mode }) => ({
  plugins: [react()],
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
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../../packages/tv-core", "../web/public"] },
  },
}));
