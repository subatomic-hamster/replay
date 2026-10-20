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
// ponytail: the API does not tell the TV where apps/web's phone pages live yet, so the
// QR handoff says so on Fire TV; read it from the API (or BuildConfig) when it does.
export const WEB_BASE: string = "";
// ponytail: watch positions live in app memory on Fire TV (lost when the app is killed);
// add a getString/setString pair to ReplaySettings if they must survive a restart.
let resume = "";
export const loadResume = () => resume;
export const saveResume = (value: string) => {
  resume = value;
};
