import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // packages/tv-core (shared with apps/tv) sits outside this app's root.
  server: {
    port: 5173,
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../../packages/tv-core"] },
  },
});
