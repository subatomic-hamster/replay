// The shared §4.6 client (packages/tv-core) bound to this build's config. The API base and
// key can change at runtime (Settings screen), so `api` is a live binding rebuilt on change.
import { createHttpApi, sessionWsUrl, type ReplayApi } from "../../../packages/tv-core/src/api";
import { mockApi } from "../../../packages/tv-core/src/mock";
import {
  BUILD_API_BASE,
  BUILD_API_KEY,
  MOCK_API,
  loadApiBase,
  loadApiKey,
  saveApiBase,
  saveApiKey,
} from "./platform/config";

let base = loadApiBase() || BUILD_API_BASE;
let key = loadApiKey() || BUILD_API_KEY;

export let api: ReplayApi = MOCK_API ? mockApi : createHttpApi(base, key);

const rebuild = () => {
  if (!MOCK_API) api = createHttpApi(base, key);
};

export const apiBase = () => base;
export const apiKey = () => key;

export const wsUrl = (idOrCode: string) => sessionWsUrl(base, idOrCode);

/** A client for `candidate` without switching to it (the Settings screen's connection test). */
export const probeApi = (candidate: string) => createHttpApi(candidate, key);

/** "10.0.0.5:8000/" → "http://10.0.0.5:8000"; null when it is not an http(s) URL. */
export function normalizeApiBase(input: string): string | null {
  let v = input.trim().replace(/\/+$/, "");
  if (!/^[a-z]+:\/\//i.test(v)) v = `http://${v}`;
  return /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?(\/[\w.~/-]*)?$/.test(v) ? v : null;
}

export function setApiBase(value: string) {
  base = value;
  saveApiBase(value);
  rebuild();
}

/** D-80: the X-Replay-Key that cloud mode needs for POST /games; kept on the device. */
export function setApiKey(value: string) {
  key = value;
  saveApiKey(value);
  rebuild();
}

/** On screen only the last 4 characters of the key show. */
export const maskKey = (k: string) => "•".repeat(Math.min(k.length, 4)) + (k.length > 4 ? k.slice(-4) : "");

/** D-80: the deployed build's `config.json` apiBase. A base saved in Settings still wins. */
export function setDefaultApiBase(value: string) {
  if (loadApiBase()) return;
  base = value;
  rebuild();
}
