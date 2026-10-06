// The contract between PlayerSurface and the platform media element
// (platform/Media.web.tsx = <video>, platform/Media.native.tsx = react-native-video).
import type { Ref } from "react";

export interface MediaHandle {
  /** Ask for playback; held and retried until the element can actually play. */
  play(): void;
  pause(): void;
  seek(t: number): void;
  /** Last media time the platform reported (the clock extrapolates between reports). */
  currentTime(): number;
  duration(): number;
  /** False while a play request is pending, so a second toggle cancels it. */
  paused(): boolean;
}

export interface MediaProps {
  src: string;
  muted?: boolean;
  /** Restart at the end (the Replay view loops a highlight). */
  loop?: boolean;
  onEnded?: () => void;
  /** The source failed to load or play (native only so far; the web <video> never calls it). */
  onError?: (message: string) => void;
  ref?: Ref<MediaHandle>;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
