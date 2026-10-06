// Native (Fire TV) config. Metro has no import.meta.env, so the API base is read from
// app.json's `apiBase` — set it to the LAN address of the machine running services/api
// before `gradlew assembleRelease`. No secrets here: the optional demo key is not
// shipped in the APK.
import app from "../../app.json";

export const API_BASE: string = app.apiBase;
export const API_KEY = "";
export const MOCK_API = false;
export const FOLLOWCAM_MODE: "client" | "rendition" = "client";
