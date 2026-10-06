// The shared §4.6 client (packages/tv-core) bound to this build's config.
import { createHttpApi, sessionWsUrl, type ReplayApi } from "../../../packages/tv-core/src/api";
import { mockApi } from "../../../packages/tv-core/src/mock";
import { API_BASE, API_KEY, MOCK_API } from "./platform/config";

export const api: ReplayApi = MOCK_API ? mockApi : createHttpApi(API_BASE, API_KEY);

export const wsUrl = (idOrCode: string) => sessionWsUrl(API_BASE, idOrCode);
