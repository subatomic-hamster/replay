# Fire TV: build, side-load, first run

The Fire TV app (`apps/tv`, react-native-tvos 0.87, D-57/D-60/D-64/D-65) first ran on a real
device on 2026-10-21: a Fire TV Stick (AFTSS) against the AWS deployment (section 0). The
checklist below is for whoever installs it next. Tick each box, note what you saw, and
attach the logcat.

## 0. AWS build on a Fire TV Stick (2026-10-21)

**Build for the AWS deployment** (on hfbox, in your own copy of the repo, Gradle offline):

```sh
source /workspace/wt/replay-env/env.sh && source /workspace/wt/replay-env/android/env.sh
cd apps/tv && pnpm install --frozen-lockfile --offline
cd android && echo "sdk.dir=$ANDROID_HOME" > local.properties
export REPLAY_API_BASE=https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws
REPLAY_API_KEY=$(cat /workspace/wt/replay-env/api-key); export REPLAY_API_KEY
flock /workspace/wt/replay-env/.cpu.lock ./gradlew --offline assembleRelease \
  -PreactNativeArchitectures=armeabi-v7a
```

- The key is read inside the shell, from the box file (0600) or from SSM
  (`aws ssm get-parameter --name /replay/api-key --with-decryption --query Parameter.Value
  --output text`, profile `replay`). Never put it on a command line, in `gradle.properties`
  or in git. **The APK then contains the key**: keep it off shared drives and stores; anyone
  with it can call the API as the TV.
- `armeabi-v7a` alone suits every 32-bit stick (AFTSS, 4K, Lite): 18.5 MB, about a minute of
  Gradle time. Leave the flag out for both ABIs.
- Debug-signed unless the four `REPLAY_RELEASE_*` values are set (section 2).
- Side-load over USB or `adb connect`: `adb install -r app-release.apk`, then
  `adb shell am start -n com.replaytv/.MainActivity`. Settings shows the baked address and
  `••••` plus the key's last 4 characters.

**Network.** The stick ran on GTvisitor (open, client-isolated; plain internet), a temporary
path. On GT's device network the stick is unregistered: DNS and ping work and Android calls
the Wi-Fi validated, but HTTP gets a 302 to `portal.nac.gatech.edu/guest/legacy_auth.php`
and HTTPS to any host is answered with GT's own `web-prod.noc.gatech.edu` certificate, so
every call fails with "Network request failed" (Settings: "Not reachable"; the Fire TV
launcher: "Network Unavailable"). eduroam connects on this stick (802.1x EAP) but hits the
same `legacy_auth` portal. Register the stick's MAC with GT, or use GTvisitor.

**Verified on the stick** (AFTSS "sheldon", Fire OS 7.7.1.6 = Android 9, 32-bit, ~900 MB RAM,
1080p; APK sha256 `8d7a7d28…`, USB, keys sent with `adb shell input keyevent`):

- Installs as `armeabi-v7a`; Hermes and Fabric start with no JS or native errors, no OOM or
  low-memory kills in logcat.
- Home loads the live games from the AWS API, with hero art and card thumbnails; processing
  and "Waiting for the upload" games show their state. Settings: "Connected".
- Player: Media3 on the MTK hardware AVC decoder into the TextureView; transport with the
  court-line timeline and moment notches, hides after 5 s.
- Tap Left/Right: ±10 s preview with the storyboard sprite or the moment's thumb and its
  label (snap), commit after the 600 ms linger, playback resumes. Fast-forward: ×2 scrub with
  a live sprite preview, Select commits.
- Moments row (Down): thumbs, player filters, Select jumps and plays.
- Do more (Up): Follow player chips (the picture zooms and pans to follow, "Following
  Player 2", Back stops), Stats side panel over the video (box score, shot chart, Review),
  On your phone (Clip, Tag, Review, Search).
- Phone QR, decoded from a screenshot: `https://d2454ty37m7cp7.cloudfront.net/p/<id>?job=clip&t=..`
  with the `#k=` token in the fragment; the screen shows only `host/p/<id>`.
- Add game: sport tiles, then the upload QR (`https://d2454ty37m7cp7.cloudfront.net/u/<id>`,
  token in the fragment, not on screen) and "Waiting for your phone…".
- Back peels the player's layers, then Home, then exits to the launcher.
- Resume: Home offers "Resume 0:11 / Start over" after a force-stop and relaunch
  (SharedPreferences).

**Measured** (device clock: `date` before raw `screencap` loops, key times from logcat):

| what | value |
|---|---|
| cold start, `am start -W` TotalTime (first frame) | 0.74–1.7 s, typically ~1.0 s |
| cold start to Home with live games | ~5 s (was ~6.6 s before the cookie-jar fix) |
| Home focus move (Right) to the new card drawn | ≤ 0.13 s |
| open a game (Select released) to first video frame | ~3.2 s (API reads ~1.8 s, then 1.4 s to the first decoded frame) |
| tap seek: preview on screen | ≤ 0.3 s |
| tap seek: picture at the new point | ≤ 0.35 s after the commit (≤ 0.94 s after the key, 600 ms of it the linger) |
| follow-cam, `gfxinfo` over 8 s | 393 frames, 0.76 % janky, p90 11 ms |
| memory at Home / Settings, no video | PSS 73–76 MB, RSS 134 MB |
| memory during playback (`dumpsys meminfo`) | TOTAL PSS 165–177 MB (Graphics 56–78 MB), RSS 134 MB |

**Device bugs found and fixed:**

- No remote key reached JS: Android sends keys only down the focused-view chain and nothing
  in the app is natively focusable. The app root (`App.tsx`) is `focusable` with
  `hasTVPreferredFocus` on native.
- A screen's key handler could jump back above its error banner (`useDpad` re-pushed a
  handler whenever its identity changed); the stack slot now depends only on mount/enable
  (`input.ts`; TV-16 covers it). Back on the library's banner exits the app (`ui.tsx`).
- The first API request waited ~1.9 s for WebView to load: React Native's cookie jar asks
  WebView's `CookieManager`. The app sets an OkHttp client factory with a no-op cookie jar
  (`MainApplication.kt`); fetch, Fresco and react-native-video all use it.
- ExoPlayer's own controller (⏮ ⟲ ▶ ⟳ ⏭) showed over the black picture while a video loaded:
  the patched `PlayerView` started with `useController = true` until player init. It now
  starts off (`patches/react-native-video@6.19.3.patch`, lockfile hash updated).

**Not verified / known device issues:**

- Hold-to-seek tiers and the 120 ms key repeat: `adb shell input keyevent --longpress` is
  not a real hold (it acts as a tap). Needs a physical remote.
- Highlights / Condensed, Angles and Free view: none of the live games has them.
- Replay did not show in Your Apps & Channels or the App Library (cause unknown), though
  `LEANBACK_LAUNCHER` resolves with the banner; start it with `am start` for now.
- Two ~800 ms main-thread frames (`Davey!`) when a game opens, and a ~930 ms one when Home
  first draws: Fabric mounting the screen. Not optimised.
- `adb shell input` takes ~1 s per call on this stick (JVM start), so key timings were
  measured from logcat's `injectKeyEvent`, not from the computer.

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

None of these had been observed on hardware before section 0. Tick each one only once you
have seen it.

- [x] Playback works on Fire OS (react-native-video / ExoPlayer): the wide rendition on the
  AFTSS stick, hardware AVC decode (section 0).
- [x] TextureView follow-cam transforms render (the react-native-video patch, D-64).
- [x] Their GPU cost is acceptable (gfxinfo janky frames, no dropped playback): 0.76 % janky.
- [x] Remote key codes reach the app as mapped in `apps/tv/src/platform/keys.native.ts`
  (after the root-focus fix; arrows, Select, Back, Play/Pause and Fast-forward sent with
  `adb shell input keyevent`; a physical remote not yet tried).
- [ ] The 120 ms JS key-repeat for held arrows starts and stops correctly.
- [ ] Rapid angle cuts work. Each cut is a new source load of a 720p file with no audio track.
- [x] Seek latency is acceptable: the picture lands ≤ 0.35 s after a seek commits.
- [ ] Decode of every rendition works (wide, broadcast, replay angles, condensed, 9:16). Only
  wide seen so far.
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
