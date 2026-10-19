// Codegen spec (package.json codegenConfig) for the app-local Turbo Module in
// android/app/src/main/java/com/replaytv/ReplaySettingsModule.kt: the API base and API key
// persisted in SharedPreferences, and their build-time defaults (REPLAY_API_BASE and
// REPLAY_API_KEY, baked into BuildConfig).
// Synchronous on purpose: config.native.ts reads it once before the first render.
import type { TurboModule } from "react-native";
import { TurboModuleRegistry } from "react-native";

export interface Spec extends TurboModule {
  /** The saved API base, or "" when none was saved. */
  getApiBase(): string;
  setApiBase(value: string): void;
  /** REPLAY_API_BASE at build time, or "". */
  getBuildApiBase(): string;
  /** The saved X-Replay-Key, or "" when none was saved. */
  getApiKey(): string;
  setApiKey(value: string): void;
  /** REPLAY_API_KEY at build time, or "". */
  getBuildApiKey(): string;
}

// `get`, not `getEnforcing`: a build without the module falls back to the build default.
export default TurboModuleRegistry.get<Spec>("ReplaySettings");
