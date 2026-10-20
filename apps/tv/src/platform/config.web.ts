/// <reference types="vite/client" />
// Web build config, from Vite env (same variables as apps/web). The Settings screen's API
// base and API key are kept in localStorage and win over VITE_REPLAY_API_BASE / _KEY.
export const BUILD_API_BASE: string =
  import.meta.env.VITE_REPLAY_API_BASE ?? "http://localhost:8000";
export const BUILD_API_KEY: string = import.meta.env.VITE_REPLAY_API_KEY ?? "";
export const MOCK_API = import.meta.env.VITE_MOCK_API === "1";
export const FOLLOWCAM_MODE: "client" | "rendition" =
  import.meta.env.VITE_FOLLOWCAM_MODE === "rendition" ? "rendition" : "client";

// try/catch: storage can be blocked (private mode); then the setting lasts for the page.
function load(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* not persisted */
  }
}

export const loadApiBase = () => load("replay.apiBase");
export const saveApiBase = (value: string) => save("replay.apiBase", value);
export const loadApiKey = () => load("replay.apiKey");
export const saveApiKey = (value: string) => save("replay.apiKey", value);
/** Watch positions (resume.ts), as JSON. */
export const loadResume = () => load("replay.resume");
export const saveResume = (value: string) => save("replay.resume", value);
