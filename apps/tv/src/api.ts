// The shared §4.6 client (packages/tv-core) bound to this build's config. The API base can
// change at runtime (Settings screen), so `api` is a live binding that is rebuilt on change.
import { createHttpApi, sessionWsUrl, type ReplayApi } from "../../../packages/tv-core/src/api";
import { mockApi } from "../../../packages/tv-core/src/mock";
import { API_KEY, BUILD_API_BASE, MOCK_API, loadApiBase, saveApiBase } from "./platform/config";

let base = loadApiBase() || BUILD_API_BASE;

export let api: ReplayApi = MOCK_API ? mockApi : createHttpApi(base, API_KEY);

export const apiBase = () => base;

export const wsUrl = (idOrCode: string) => sessionWsUrl(base, idOrCode);

/** A client for `candidate` without switching to it (the Settings screen's connection test). */
export const probeApi = (candidate: string) => createHttpApi(candidate, API_KEY);

/** "10.0.0.5:8000/" → "http://10.0.0.5:8000"; null when it is not an http(s) URL. */
export function normalizeApiBase(input: string): string | null {
  let v = input.trim().replace(/\/+$/, "");
  if (!/^[a-z]+:\/\//i.test(v)) v = `http://${v}`;
  return /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?(\/[\w.~/-]*)?$/.test(v) ? v : null;
}

export function setApiBase(value: string) {
  base = value;
  saveApiBase(value);
  if (!MOCK_API) api = createHttpApi(value, API_KEY);
}
