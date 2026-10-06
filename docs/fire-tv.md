# Fire TV: build, side-load, first run

The Fire TV app (`apps/tv`, react-native-tvos 0.87, D-57/D-60/D-64/D-65) has **never run on
a device**. This is the checklist for the first person who installs it. Tick each box,
note what you saw, and attach the logcat.

## 1. Before you start

- A Fire TV (Stick 4K / 4K Max / Cube; the APK has `armeabi-v7a` and `arm64-v8a` code) on the
  same LAN as the computer that runs the Replay API.
- The API listening on the LAN (not just localhost), **without** `REPLAY_API_KEY` (the TV app
  sends no key):

  ```sh
  REPLAY_DATA_DIR=<data dir with processed games> \
    uv run --package replay-api uvicorn replay_api.main:app --host 0.0.0.0 --port 8000
  ```

  `make demo` builds two synthetic games if you need some (README "Quickstart"). Check from
  another device: `curl http://<computer-ip>:8000/games`. Media URLs are built from the
  address the TV calls, so no extra configuration is needed.
- `adb` (Android platform-tools) on your computer.

## 2. Build the APK

```sh
cd apps/tv && pnpm install --frozen-lockfile      # applies the react-native-video TextureView patch (D-64)
cd android && echo "sdk.dir=$ANDROID_HOME" > local.properties
REPLAY_API_BASE=http://192.168.1.20:8000 ./gradlew assembleRelease   # REPLAY_API_BASE is optional
# → app/build/outputs/apk/release/app-release.apk
```

- **Prebuilt APK (box, not committed):** `/workspace/wt/replay-ops/apk/replay-tv-0.2.0-scene-release.apk`,
  built from d352ad3 (Free view JS + native GL scene view, D-77), debug-signed. Copy it off the box and skip the build.
- **`REPLAY_API_BASE`** (env var or `-PREPLAY_API_BASE=`) is the address baked in as the
  default. Leave it out and the app opens Settings on first run. Either way the address can
  be changed on the TV without a rebuild (section 4).
- **Signing.** Release signing reads four values from env vars or Gradle properties, never
  from the repo. Put them in `~/.gradle/gradle.properties` (outside the repo) or export them:

  | name | value |
  |---|---|
  | `REPLAY_RELEASE_STORE_FILE` | absolute path of your keystore (`.jks` / `.keystore`) |
  | `REPLAY_RELEASE_STORE_PASSWORD` | keystore password |
  | `REPLAY_RELEASE_KEY_ALIAS` | key alias |
  | `REPLAY_RELEASE_KEY_PASSWORD` | key password |

  If any is missing, the release APK is signed with the **debug** keystore and the build log
  says `WARNING: REPLAY_RELEASE_STORE_FILE / ... are not all set`. That is fine for
  side-loading, not for the Appstore. To make your own key (keep it out of the repo;
  `*.keystore` is git-ignored except the debug one):

  ```sh
  keytool -genkeypair -v -keystore ~/keys/replay-tv.jks -alias replay-tv \
    -keyalg RSA -keysize 2048 -validity 10000
  ```

  An APK signed with a different key cannot update an installed one: `adb uninstall
  com.replaytv` first (this also clears the saved API address).

## 3. Side-load

1. On the Fire TV: Settings → My Fire TV → Developer options → **ADB debugging** on, and
   **Apps from Unknown Sources** (or "Install unknown apps") on. If Developer options is
   missing: Settings → My Fire TV → About → select the device name 7 times.
2. Its IP address: Settings → My Fire TV → About → Network.
3. From your computer:

   ```sh
   adb connect <tv-ip>:5555          # accept the "Allow USB debugging?" prompt on the TV
   adb devices                       # <tv-ip>:5555  device
   adb install -r replay-tv-*.apk
   adb shell am start -n com.replaytv/.MainActivity
   ```

   "Replay" also appears under Apps (it declares the `LEANBACK_LAUNCHER` category and a
   banner).

## 4. First run: set the API address

- [ ] With no `REPLAY_API_BASE` in the build, the app opens **Settings** with the address
  keyboard already open. Otherwise: Library → Up → Right to **Settings** → Select. A wrong
  address shows "Could not reach the Replay API"; Right → **Settings** from there.
- [ ] Type the address with the on-screen keyboard (arrows + Select; the top row has
  `http://`, `192.168.`, `10.0.`, `:8000`, `.local`; DEL deletes, Back cancels), then SAVE.
  `http://` is added if you leave it out.
- [ ] Settings then calls `GET /games` and shows "Connected · N games" (or the error).
  **Done** returns to the library.
- [ ] Force-stop and reopen (`adb shell am force-stop com.replaytv`, then the `am start`
  above): the address is still there (it is kept in the app's SharedPreferences).

## 5. What to check

Open a ready game from the library. For each item, write down what happened.

- [ ] **Playback**: the wide video starts, plays smoothly, and has sound. Select toggles
  play/pause.
- [ ] **Follow-cam (TextureView, D-64)**: pause (Select) → select mode with boxes on the
  players → pick one → Select. The picture zooms and pans to follow the player. It must be
  the video that moves, not a black box or a frozen frame. Also try Spotlight (Up → Playback ▸
  → Spotlight). Note any jank and run `adb shell dumpsys gfxinfo com.replaytv` after a
  minute of follow-cam (janky frames %).
- [ ] **D-pad and long-press**: arrows, Select, Back, Menu (opens the action row), Play/Pause,
  Rewind/Fast-forward (±10 s). Hold Left/Right during playback: it should keep scrubbing
  (a JS repeat every 120 ms) and stop as soon as you let go. Hold an arrow in a list (Players,
  Clips) the same way. Back from the library exits the app.
- [ ] **Angle cuts (D-57)**: Up → Game ▸ → Replays → pick a play → Left/Right cut between
  angles. The time and the play/pause state must carry over. Cut quickly 5–10 times in a row:
  no stall, crash or "Video unavailable".
- [ ] **Seek latency**: Right (+5 s scrub), Fast-forward (+10 s), and the event jumps
  (Up → Playback ▸ → ◀ Event / Event ▶). Note roughly how long the picture takes to update.
- [ ] **Decode**: the broadcast rendition (Up → Broadcast) at 1080p, and the condensed game
  on a net-sport game (Rallies). Any green frames, stutter or audio drift?
- [ ] **Memory**: after ~10 minutes of use, `adb shell dumpsys meminfo com.replaytv | head -30`
  (TOTAL PSS). Does the app get killed when you go Home and come back?

### Unverified items from OVERNIGHT_REPORT §9 P0 item 1

None of these has ever been observed on hardware. Tick each one only once you have seen it.

- [ ] Playback works on Fire OS (react-native-video / ExoPlayer).
- [ ] TextureView follow-cam transforms render (the react-native-video patch, D-64).
- [ ] Their GPU cost is acceptable (gfxinfo janky frames, no dropped playback).
- [ ] Remote key codes reach the app as mapped in `apps/tv/src/platform/keys.native.ts`.
- [ ] The 120 ms JS key-repeat for held arrows starts and stops correctly.
- [ ] Rapid angle cuts work. Each cut is a new source load of a 720p file with no audio track.
- [ ] Seek latency is acceptable.
- [ ] Decode of every rendition works (wide, broadcast, replay angles, condensed, 9:16).
- [ ] Memory stays bounded over a session.

### Free view (2.5D scene, D-75): unverified on hardware

The native renderer (`com.replaytv.scene.SceneView`: GLSurfaceView + OpenGL ES 3.0, ExoPlayer
decoding `atlas.mp4` into a `GL_TEXTURE_EXTERNAL_OES` texture; docs/scene-format.md) compiles,
registers as the Fabric component `ReplaySceneView`, and its shaders and camera maths pass
`bash apps/tv/android/scene-check.sh` on the build box. Nothing below has been seen on a
device. Needs a game with scene packages (the replay manifest's `scene_url` is set). Errors
are logged under the `ReplayScene` tag (add `ReplayScene:V` to the logcat filter in section 6).

- [ ] **Opens**: Replays → a play → Down. The scene (court, players) covers the picture — not
  a black or transparent rectangle (a SurfaceView punched over the paused TextureView angle).
  No `ReplayScene` error ("shaders: …", "atlas video: …", "plate …") in logcat.
- [ ] **Orientation**: not upside down or mirrored, and at the `real` preset it lines up with the
  video angle you came from (SurfaceTexture transform, v-down uv convention).
- [ ] **Players**: cut-outs move with the play, stand on their shadows, never show another
  player's picture for a frame (atlas frame ↔ layout frame sync through ExoPlayer's frame
  metadata), and have clean edges with no grey box around them (mask alpha after the
  decoder's YUV → RGB, limited range).
- [ ] **D-pad**: Left/Right orbit, Up/Down change height (Menu switches them to zoom),
  Rewind/Fast-forward cycle presets, Select/Play-Pause pause, Back leaves. Motion glides
  (eased) and stops at the envelope edges with the edge bar; a held arrow keeps moving and
  stops on release.
- [ ] **Time lock**: entering at time t shows the same moment as the angle; Back resumes the
  angle where the scene was (±0.1 s). Pause and resume inside the scene work; the play loops
  without a stall.
- [ ] **Performance**: `adb shell dumpsys gfxinfo com.replaytv` after a minute of orbiting
  (janky frames %). Real packages have atlases up to 2048×1024: they must decode at the
  play's frame rate (no stutter, players not lagging the shadows).
- [ ] **Lifecycle**: Home and back to the app while in free view: the scene comes back (GL
  context kept or rebuilt) and does not crash.
- [ ] **Memory**: enter and leave free view 10 times; TOTAL PSS (`dumpsys meminfo`) settles
  (the player is released and the plate textures deleted each time).

## 6. Grab the logs

```sh
adb logcat -c                                    # clear, then reproduce the problem
adb logcat -v time ReactNativeJS:V ReactNative:V ExoPlayerImplInternal:V ExoPlayerImpl:V \
  MediaCodec:W AndroidRuntime:E '*:S' | tee replay-tv-logcat.txt
# everything from the app's process only:
adb logcat -v time --pid=$(adb shell pidof -s com.replaytv) > replay-tv-full.txt
```

A crash shows up as `AndroidRuntime: FATAL EXCEPTION`. JS errors and `console.log` show up
under `ReactNativeJS`. Attach the files together with the ticked checklist.
