// The §4.6 client is shared with apps/tv (packages/tv-core/src/api.ts); this file only
// binds it to the Vite env config.
import { API_BASE, API_KEY, MOCK_API } from "../config";
import { mockApi } from "./mock";
import {
  createHttpApi,
  sessionWsUrl as wsUrl,
  type ReplayApi,
} from "../../../../packages/tv-core/src/api";

export {
  ApiError,
  type CalibrationPayload,
  type ReplayApi,
} from "../../../../packages/tv-core/src/api";

export const httpApi: ReplayApi = createHttpApi(API_BASE, API_KEY);

export const api: ReplayApi = MOCK_API ? mockApi : httpApi;

/** H4: the phone companion connects with the 4-digit code, the TV with the session id —
 *  the WS route accepts either (D-16). */
export function sessionWsUrl(idOrCode: string): string {
  return wsUrl(API_BASE, idOrCode);
}
