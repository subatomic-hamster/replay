/// <reference types="vite/client" />
// Web build config, from Vite env (same variables as apps/web). The Settings screen's API
// base is kept in localStorage and wins over VITE_REPLAY_API_BASE.
export const BUILD_API_BASE: string = import.meta.env.VITE_REPLAY_API_BASE ?? "http://localhost:8000";
export const API_KEY: string = import.meta.env.VITE_REPLAY_API_KEY ?? "";
export const MOCK_API = import.meta.env.VITE_MOCK_API === "1";
export const FOLLOWCAM_MODE: "client" | "rendition" =
  import.meta.env.VITE_FOLLOWCAM_MODE === "rendition" ? "rendition" : "client";

const KEY = "replay.apiBase";

// try/catch: storage can be blocked (private mode); then the setting lasts for the page.
export function loadApiBase(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveApiBase(value: string) {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* not persisted */
  }
}
