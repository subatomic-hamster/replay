# Alexa voice for Replay (sideloaded Fire TV app): research and recommendation

Accessed 2026-10-21. Sources are Amazon developer docs unless noted. "Not stated" means the page was fetched and is silent; it is not evidence either way. Items marked **TEST** must be verified on the real AFTSS before relying on them.

## 1. Mechanisms

### (a) MediaSession transport controls: best fit for pause / rewind / next

- Fire TV voice-enables transport controls via Android Media Session, no VSK needed. Covers play, pause, rewind, fast-forward, next, previous, from both the remote mic (near-field) and Echo (far-field). https://developer.amazon.com/docs/fire-tv/mediasession-api-integration.html
- Manifest: add `com.amazon.permission.media.session.voicecommandcontrol`. "Not required for Fire OS 14 and later", so it IS needed on Fire OS 7.7. Optional `<meta-data android:name="com.amazon.voice.supports_background_media_session" android:value="true"/>` opts in to routing "to the most recently used app", with the requirement to follow audio-focus rules (same page).
- Callbacks: `onPlay`, `onPause` ("stop" is mapped to pause; implement `onStop` too), `onSkipToNext` / `onSkipToPrevious`, and `onSeekTo(pos)` for rewind/fast-forward/restart. Relative times are resolved by Alexa and passed as absolute ms; default is 10 s when no duration is spoken. So "rewind 30 seconds" arrives as `onSeekTo(current-30000)` (same page). Absolute-time requests ("go to 2:15:00") do not set position (same page).
- Amazon calls MediaSession preferred over VSK PlaybackController: "same features with less latency and a more consistent customer experience". https://developer.amazon.com/docs/video-skills-fire-tv-apps/integrate-with-mediasession-app-only.html
- Docs are silent on Appstore status, sideloading, latency, and test procedure. **TEST**: whether a debug-signed sideloaded app gets the permission granted and receives commands. The permission appears to be an ordinary manifest permission, but nothing confirms it is not signature-restricted. react-native-video exposes a MediaSession on Android; verify whether its session is the one that is active (it must be `setActive(true)` with a PlaybackState that is PLAYING). Relevant known doc caveat: Cordova/web wrappers are outside the documented scope; native Android is covered.
- Does NOT cover "export a highlight reel" or any custom phrase. Unsupported commands get "Sorry, that command is not supported."

### (b) VSK for Fire TV: not viable

- "No new partners will be onboarded to Video Skills Kit (VSK)"; catalog integration is a prerequisite and is "available to select partners only"; cloudside integration needs approval from an Amazon representative. https://developer.amazon.com/docs/video-skills-fire-tv-apps/introduction.html
- Appstore requirement is not stated, but the onboarding block alone rules it out. Do not pursue.

### (c) Custom Alexa skill (development stage): the only path for "export a highlight reel"

- Dev-stage skills are testable on devices signed in to the same Amazon account (a skill is in one stage at a time; Development must be selected via the Test tab). https://developer.amazon.com/docs/devconsole/test-your-skill.html ; https://developer.amazon.com/docs/custom-skills/test-and-debug-a-custom-skill.html (the Alexa app is auto-logged in to the device's account on Fire OS devices).
- Evidence for Fire TV Stick specifically is thin. Amazon's blog says "Fire TV Cube can enable all published Alexa skills" (https://developer.amazon.com/blogs/alexa/post/5ed87ab4-16ee-4e7d-8f6e-6c45a844b75d/best-practices-for-building-alexa-skills-for-fire-tv-cube); a hobbyist write-up says custom skills work on Fire TV like Echo (hackster.io, corroboration only). No Amazon page found stating that a Fire TV Stick voice-remote request invokes third-party custom skills in dev stage. **TEST this first**, with the skill's own phrasing ("Alexa, ask Replay to ...") through the remote's voice button. Echo or the Alexa phone app under the same account is the backup trigger.
- Skill -> app relay: nothing in Alexa reaches an arbitrary sideloaded app directly. Relay via our backend (skill endpoint writes a command; TV polls). Latency is not documented anywhere; expect Alexa speech handling ~1-3 s plus up to one poll interval (see section 3). Alexa docs give no response timeout figure on the pages fetched; the commonly cited ~8 s limit is not confirmed here, so keep the skill handler fast (a single DynamoDB/S3 or in-memory write).

### (d) Alexa+ / LLM app actions for Fire TV

- Found no developer documentation for third-party Alexa+ actions on Fire TV. Consumer news only: Alexa+ hub updates start reaching US customers in November on a limited device list (ppc.land summary of the Sept 30, 2026 announcement, secondary source). Not usable for this demo. Fire TV Integration SDK release notes show no such feature. https://www.developer.amazon.com/docs/fire-tv/firetv-integration-release-notes.html

## 2. Custom skill: steps and requirements

**Console vs CLI.** Developer console is fastest for one skill with one intent set: Create skill -> Custom -> "Provision your own" -> paste the interaction model JSON -> set endpoint -> Build -> Test tab -> Development. ASK CLI (`npm i -g ask-cli`, Node 14+, `ask configure` opens browser login; `ask new`; `ask deploy` auto-enables testing; `ask dialog`) https://developer.amazon.com/docs/smapi/quick-start-alexa-skills-kit-command-line-interface.html . CLI needs the vendor ID, which "needs complete information including phone number and credit card" in the developer account (same page). For a one-day job, use the console; ASK CLI adds a login step the user must do interactively anyway.

**Invocation name** (en-US rules): lowercase letters, spaces, possessive apostrophes only; no "alexa/amazon/echo/skill/app"; no launch phrases or connecting words; one-word names are not allowed unless brand-unique with proof of ownership; two-word names cannot include an article or preposition; numbers spelled out. https://developer.amazon.com/docs/custom-skills/choose-the-invocation-name-for-a-custom-skill.html . Implication: single word "replay" is risky/may be rejected at certification, but dev-stage testing is not certification. Use a two-word name such as "replay court" or "game replay" to be safe. The spoken phrase then becomes "Alexa, ask replay court to export a highlight reel".

**Endpoint.** HTTPS on port 443, Amazon-trusted cert, domain in the cert SAN; self-signed is for testing only. Console endpoint options: trusted CA cert, wildcard-cert subdomain, or self-signed. https://developer.amazon.com/docs/custom-skills/host-a-custom-skill-as-a-web-service.html . Our Lambda Function URL (`https://<id>.lambda-url.us-east-1.on.aws`) is HTTPS with an AWS/Amazon-issued wildcard cert, so choose "sub-domain of a domain that has a wildcard certificate". This is an inference, not documented for Function URLs. **TEST** in the console (it validates on save). If rejected, fall back to an Alexa-hosted/Lambda ARN endpoint (a thin Lambda in us-east-1 that forwards to the API), which is the standard documented route.

**Request verification (mandatory for HTTPS endpoints).** Verify `SignatureCertChainUrl` and `Signature-256` headers over the raw body, and reject timestamps off by more than 150 s with HTTP 400 (same page). Use the `ask-sdk-webservice-support` / `ask-sdk-verifiers` equivalent, or in Python `flask-ask-sdk`/`ask-sdk-webservice-support`. Note Lambda Function URL passes the raw body; verify against the exact bytes, not re-serialised JSON. If the skill is behind a Lambda-ARN endpoint instead, the trigger is restricted by Alexa Skills Kit event source (skill ID), and signature checks are unneeded.

**Account linking: not needed.** `userId` is generated when the skill is enabled and is stable until disabled/re-enabled; `deviceId` is in `context.System.device`; the access token exists only with linking. https://developer.amazon.com/docs/custom-skills/request-and-response-json-reference.html . Pairing without linking:

1. TV (Settings or Home) shows a 4-digit pairing code that expires in ~5 min.
2. User says "Alexa, ask replay court to pair code 4 8 2 9" (slot AMAZON.FOUR_DIGIT_NUMBER).
3. Skill handler records `userId` (and `deviceId`) against that TV's session; TV polls and learns it is paired.
4. Later requests carry `userId`; backend routes the command to the paired TV. Caveat: userId changes if the skill is disabled and re-enabled; re-pair then. Single user, one TV: also acceptable to hardcode the allowlist of the demo user's `userId` in an env var after the first request shows it in logs (simplest for a hackathon).

**Testing.** Console Test tab simulator (text or mic) works without any device and exercises the full backend path. Device test: dev skill must be in Development stage on the same account that the Fire TV is registered to. User must be signed in; the locale of the skill (en-US) must match the device's language (not covered by the docs found; standard Alexa behaviour, **TEST**).

**What the user must do personally** (we cannot use their credentials):

1. Sign in to developer.amazon.com with the Amazon account that the Fire TV is registered to (create a developer account if needed; free).
2. Create the skill (or run `ask configure` and `ask deploy`) and paste the model JSON and endpoint URL we provide.
3. Test tab -> Development; confirm the skill appears under Alexa app -> Skills & Games -> Your Skills -> Dev.
4. Try the phrase from the Fire TV remote voice button; report what Alexa says.
5. Whatever the skill's first real request is, read the `userId` from CloudWatch (or do the pairing step).

## 3. Recommendation

**Two layers, both done in about a day:**

1. **Custom skill relay** (the demo beat "export a highlight reel", "clip that"). ~5-7 h: interaction model, Lambda route, TV poller and QR reaction, signature verification, console setup by the user (~30 min).
2. **MediaSession callbacks** for pause / rewind N seconds / next moment. ~2-3 h in the RN app, probably a small native module or react-native-video's session; the manifest permission and meta-data are in the app's manifest. Risk is the sideload/permission uncertainty above; if it fails, drop it, nothing else depends on it.

**Fallback if live voice fails (honest, not faked):** an on-screen remote shortcut, for example long-press Select, or the dedicated "Voice" chip on Home, triggers the same TV action (identical code path to the poll handler), shown with a visible label such as "Alexa unavailable: using remote". Also have the phone page (/p/{id}) button as a third trigger. The voice beat is shown live; if it does not respond within ~5 s, say so on stage and press the fallback. Do not play pre-recorded audio. Also record the console-simulator run as secondary evidence of the skill working (labelled as the simulator).

**Minimum interaction model** (invocation `replay court`):

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "replay court",
      "intents": [
        {
          "name": "ExportIntent",
          "slots": [],
          "samples": [
            "export a highlight reel",
            "export the highlight reel",
            "make a highlight reel",
            "export a reel",
            "export highlights",
            "send me a highlight reel"
          ]
        },
        {
          "name": "ClipIntent",
          "slots": [],
          "samples": [
            "clip that",
            "clip the last play",
            "save that clip",
            "clip the last thirty seconds"
          ]
        },
        {
          "name": "PairIntent",
          "slots": [{ "name": "code", "type": "AMAZON.FOUR_DIGIT_NUMBER" }],
          "samples": [
            "pair code {code}",
            "pair with {code}",
            "my code is {code}"
          ]
        },
        { "name": "AMAZON.HelpIntent", "samples": [] },
        { "name": "AMAZON.StopIntent", "samples": [] },
        { "name": "AMAZON.CancelIntent", "samples": [] },
        { "name": "AMAZON.FallbackIntent", "samples": [] }
      ]
    }
  }
}
```

Utterances are used as "Alexa, ask replay court to export a highlight reel" (or "tell replay court to ..."). The skill responds "Okay, check your TV." (short, so Alexa finishes quickly; set `shouldEndSession: true`).

**Backend/TV contract (FastAPI):**

- `POST /alexa` (skill endpoint): verify cert chain/signature/timestamp (400 on failure); read `userId` and `deviceId`; handle `LaunchRequest`, `PairIntent`, `ExportIntent`, `ClipIntent`; reject unpaired userId (say "Pair first"); write a command record `{id, kind: "export"|"clip", userId, ts, expires_at: ts+60s}`; respond with speech.
- `POST /tv/pair/start` -> `{code, expires_in: 300}` (TV shows the code; store hash + TV token).
- `GET /tv/commands?since=<last_id>` (TV token header; ~1 s poll while Watch screen is foregrounded, 3-5 s otherwise, stop while backgrounded) -> `[{id, kind, ts}]`. Poll interval 1 s gives ~0.5 s average added latency; Function URL + Lambda cost is negligible for one device. Long-poll (hold for up to 20 s) is a lower-latency upgrade: Lambda cost only, but the Function URL has no streaming need.
- `POST /tv/commands/{id}/ack` marks consumed so a command fires once; the TV discards any command older than 60 s (stale-voice protection).
- On `export`, TV calls the existing export route and shows the QR; on `clip`, it calls the existing clip route with the current playhead (dedupe by command id).
- Security: signature verification mandatory; reject mismatched `session.application.applicationId` (skill ID in env var); allowlist of `userId`s; TV token (random, issued at pairing); per-token rate limit ~10 req/s on /tv, per-user 10 commands/min on /alexa; store commands in-memory or DynamoDB with TTL (Lambda instances do not share memory, so use DynamoDB/S3 object with short TTL; do not rely on in-process state). Never log presigned URLs.
- Expected end-to-end: speech end -> TV reaction ~2-4 s (not documented by Amazon; measure on the real device).

## 4. Risks

- Custom skill invocation from a Fire TV Stick remote is under-documented; test it first, before any other work. Echo or phone Alexa app are fallbacks.
- Lambda Function URL acceptance as a skill endpoint is untested; ARN-based forwarder is the fallback.
- MediaSession routing to a sideloaded debug app is undocumented; permission behaviour unverified.
- `userId` resets on skill re-enable. Locale mismatch can hide the dev skill.
- Alexa+ rollout starts November in the US on limited devices; if the user's account is migrated early, custom-skill behaviour could change (no source; just a flagged unknown).

## Sources

- https://developer.amazon.com/docs/fire-tv/mediasession-api-integration.html
- https://developer.amazon.com/docs/video-skills-fire-tv-apps/integrate-with-mediasession-app-only.html
- https://developer.amazon.com/docs/video-skills-fire-tv-apps/introduction.html
- https://developer.amazon.com/docs/custom-skills/host-a-custom-skill-as-a-web-service.html
- https://developer.amazon.com/docs/custom-skills/choose-the-invocation-name-for-a-custom-skill.html
- https://developer.amazon.com/docs/custom-skills/request-and-response-json-reference.html
- https://developer.amazon.com/docs/devconsole/test-your-skill.html
- https://developer.amazon.com/docs/custom-skills/test-and-debug-a-custom-skill.html
- https://developer.amazon.com/docs/smapi/quick-start-alexa-skills-kit-command-line-interface.html
- https://developer.amazon.com/blogs/alexa/post/5ed87ab4-16ee-4e7d-8f6e-6c45a844b75d/best-practices-for-building-alexa-skills-for-fire-tv-cube
- https://www.developer.amazon.com/docs/fire-tv/firetv-integration-release-notes.html
- https://ppc.land/amazons-fire-tv-gains-live-content-from-40-apps-on-its-home-screen/ (secondary)
