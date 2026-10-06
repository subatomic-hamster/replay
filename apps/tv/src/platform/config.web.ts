/// <reference types="vite/client" />
// Web build config, from Vite env (same variables as apps/web).
export const API_BASE: string = import.meta.env.VITE_REPLAY_API_BASE ?? "http://localhost:8000";
export const API_KEY: string = import.meta.env.VITE_REPLAY_API_KEY ?? "";
export const MOCK_API = import.meta.env.VITE_MOCK_API === "1";
export const FOLLOWCAM_MODE: "client" | "rendition" =
  import.meta.env.VITE_FOLLOWCAM_MODE === "rendition" ? "rendition" : "client";
