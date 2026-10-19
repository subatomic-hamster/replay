import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // D-80: config.ts loads the runtime config.json with a top-level await.
  build: { target: "es2022" },
  // packages/tv-core (shared with apps/tv) sits outside this app's root.
  server: {
    port: 5173,
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../../packages/tv-core"] },
  },
});
