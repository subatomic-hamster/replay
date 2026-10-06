// Codegen spec (package.json codegenConfig, type "all") for the Fabric component in
// android/app/src/main/java/com/replaytv/scene/: the 2.5D scene package renderer
// (docs/scene-format.md) on Fire TV. Wrapped by src/scene/FreeView.native.tsx; the camera
// is the target state from src/scene/camera.ts (the same D-pad code as the web viewer); the
// view eases towards it (camera.ts easeCamera), clamps it to the envelope and draws.
import type { CodegenTypes, HostComponent, ViewProps } from "react-native";
import { codegenNativeComponent } from "react-native";

export interface NativeProps extends ViewProps {
  /** GET /games/{id}/scenes/{play_id} as JSON (absolute `url` next to every file). */
  layoutJson: string;
  /** Degrees offset from envelope.azimuth0_deg. */
  azimuth: CodegenTypes.Double;
  elevation: CodegenTypes.Double;
  distance: CodegenTypes.Double;
  roll: CodegenTypes.Double;
  fovY: CodegenTypes.Double;
  paused: boolean;
  /** Media time to start at; a later change seeks. */
  startTimeSec: CodegenTypes.Double;
  /** Media time of the atlas frame on screen (~10 Hz while playing). */
  onSceneTime?: CodegenTypes.DirectEventHandler<{ sec: CodegenTypes.Double }>;
  /** The first atlas frame is on screen. */
  onSceneReady?: CodegenTypes.DirectEventHandler<null>;
  onSceneError?: CodegenTypes.DirectEventHandler<{ message: string }>;
}

export default codegenNativeComponent<NativeProps>("ReplaySceneView") as HostComponent<NativeProps>;
