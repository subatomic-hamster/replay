// Native (Fire TV) config. The API base is what the user saved on the Settings screen
// (SharedPreferences, through the ReplaySettings Turbo Module), else the build-time default
// REPLAY_API_BASE (BuildConfig; see android/app/build.gradle), else "" = first-run Settings.
// The API key (X-Replay-Key, D-80 cloud mode) works the same way with REPLAY_API_KEY, which
// comes from the build environment only and is never committed.
import NativeReplaySettings from "../../specs/NativeReplaySettings";

export const BUILD_API_BASE: string =
  NativeReplaySettings?.getBuildApiBase() ?? "";
export const loadApiBase = (): string =>
  NativeReplaySettings?.getApiBase() ?? "";
export const saveApiBase = (value: string) =>
  NativeReplaySettings?.setApiBase(value);
export const BUILD_API_KEY: string =
  NativeReplaySettings?.getBuildApiKey() ?? "";
export const loadApiKey = (): string => NativeReplaySettings?.getApiKey() ?? "";
export const saveApiKey = (value: string) =>
  NativeReplaySettings?.setApiKey(value);
export const MOCK_API = false;
export const FOLLOWCAM_MODE: "client" | "rendition" = "client";
/** Watch positions (resume.ts), as JSON, in SharedPreferences. */
export const loadResume = (): string =>
  NativeReplaySettings?.getString("resume") ?? "";
export const saveResume = (value: string) =>
  NativeReplaySettings?.setString("resume", value);
