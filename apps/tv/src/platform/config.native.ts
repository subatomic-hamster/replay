// Native (Fire TV) config. The API base is what the user saved on the Settings screen
// (SharedPreferences, through the ReplaySettings Turbo Module), else the build-time default
// REPLAY_API_BASE (BuildConfig; see android/app/build.gradle), else "" = first-run Settings.
// No secrets here: the optional demo key is not shipped in the APK.
import NativeReplaySettings from "../../specs/NativeReplaySettings";

export const BUILD_API_BASE: string = NativeReplaySettings?.getBuildApiBase() ?? "";
export const loadApiBase = (): string => NativeReplaySettings?.getApiBase() ?? "";
export const saveApiBase = (value: string) => NativeReplaySettings?.setApiBase(value);
export const API_KEY = "";
export const MOCK_API = false;
export const FOLLOWCAM_MODE: "client" | "rendition" = "client";
