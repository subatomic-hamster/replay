# Alexa voice: setup, demo runbook and the TV contract

What it does: "Alexa, ask replay court to clip that" or "... to export a highlight reel".
This is a custom skill in the Development stage (docs/alexa-research.md §3), with no
account linking. Alexa calls our API (`POST /alexa`). The API writes a command, and the TV
picks it up by polling every second. Alexa never talks to the TV app directly.

```
Fire TV remote / Echo ──voice──> Alexa ──HTTPS, signed──> Lambda Function URL /alexa
                                                              │ verify, then write
                                                              v
                     S3 alexa/{pair,link,tv,commands,acks}.json (local mode: data/alexa/)
                                                              ^
TV app ── POST /tv/state (5 s heartbeat) ─────────────────────┤
       ── GET /tv/commands?after= (1 s poll) ─────────────────┘ -> QR panel / clip toast
```

Spoken answers say what is actually true: unpaired, no game open, a wrong code, a reel
already done. Nothing renders while Alexa waits. For `export_reel` the handler only queues
the reel job (a few S3 calls) and answers.

## 1. Before the console: deploy the API

The API needs the new routes and the `cryptography` package in the Lambda zip. Build on
hfbox and deploy as in docs/aws-deploy.md §1 and §4 (`build-api-lambda.sh`, then
`npx cdk deploy ReplayCloud`). Check it is live:

```sh
API=https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API/alexa" -d '{}'   # 400 = route is live
```

## 2. The Alexa developer console (you, signed in as the Fire TV's Amazon account)

The steps are also in `alexa/README.md`. The files to paste are in `alexa/skill-package/`.

1. Go to https://developer.amazon.com/alexa/console/ask and sign in with the **same Amazon
   account the Fire TV is registered to**. If asked, create the free developer account.
2. **Create Skill**. Name: `Replay Court`. Primary locale: **English (US)**. It must match the
   Fire TV's language (Settings > Preferences > Language: English (United States)). Type:
   **Custom**. Hosting: **Provision your own**. Template: **Start from Scratch**. Create.
3. **Build > Interaction Model > JSON Editor**. Replace everything with the contents of
   `alexa/skill-package/interactionModels/custom/en-US.json`, then **Save** and
   **Build skill**. The invocation name is `replay court`. A one-word "replay" is not
   allowed.
4. **Build > Endpoint**. Choose **HTTPS**. Default Region:
   `https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws/alexa`. SSL
   certificate type: **"My development endpoint is a sub-domain of a domain that has a
   wildcard certificate from a certificate authority"**. The Function URL serves Amazon's
   `*.lambda-url.us-east-1.on.aws` certificate. **Save**.
5. Copy the **Skill ID** (`amzn1.ask.skill.…`, under the skill name, or Endpoint > "Your
   Skill ID"), then run step 3 below.
6. **Test** tab: set "Skill testing is enabled in" to **Development**.
7. Optional: in the Alexa phone app, check Devices or More > Skills & Games > Your Skills >
   Dev. "Replay Court" should be listed.

## 3. The skill id in SSM (you run this; no redeploy needed)

```sh
aws ssm put-parameter --profile replay --region us-east-1 \
  --name /replay/alexa-skill-id --type String --value 'amzn1.ask.skill.PASTE-YOURS'
```

The skill id is not a secret, so it is a plain `String` parameter. Until the parameter
exists, `/alexa` answers 400 to everything (CloudWatch:
`alexa: rejected: skill id not configured`). The API looks the parameter up on the first
verified request after you set it, so you don't need a redeploy or a cold start. If you
change it later, force a cold start:
`aws lambda update-function-configuration --function-name <Api function> --description "alexa $(date +%F)"`.
Local mode reads `REPLAY_ALEXA_SKILL_ID` from the environment instead.

## 4. Test in the console simulator (no TV needed)

In the Test tab, type (or hold the mic):

| You type                                      | Expect                                                                |
| --------------------------------------------- | --------------------------------------------------------------------- |
| `open replay court`                           | "Your TV isn't paired yet. Say: pair code, then the code on your TV." |
| (mint a code, below)                          |                                                                       |
| `ask replay court to pair code 4829`          | "Paired with your TV. ..."                                            |
| `ask replay court to clip that`               | "Open a game on your TV first, then ask again." (until a heartbeat)   |
| (send a heartbeat, below)                     |                                                                       |
| `ask replay court to clip that`               | "Okay, clipping that on your TV."                                     |
| `ask replay court to export a highlight reel` | "Okay, making your highlight reel. Scan the code on your TV ..."      |

Stand in for the TV with curl until the TV build has the contract:

```sh
KEY=$(cat ~/.replay-api-key)   # docs/aws-deploy.md §3
curl -s -X POST "$API/tv/pair" -H "X-Replay-Key: $KEY"                 # {"code":"4829",...}
curl -s -X POST "$API/tv/state" -H "X-Replay-Key: $KEY" -H 'content-type: application/json' \
  -d '{"game_id":"g_c8b6186280ac","t":120,"playing":false}'
curl -s "$API/tv/commands" -H "X-Replay-Key: $KEY"                     # the commands, newest last
```

The simulator goes through the same endpoint, signature check and S3 state as a real
device. The JSON Output pane shows our response. A 400 shows as "There was a problem with
the requested skill's response". The reason is in CloudWatch (`/aws/lambda/<Api>`,
lines starting `alexa: rejected:`).

## 5. On the Fire TV

1. Open Replay > Settings > Pair with Alexa. The TV shows a 4-digit code (once the TV build
   has the contract below).
2. Hold the remote's mic button and say: "Alexa, ask replay court to pair code 4 8 2 9". The
   TV shows "Alexa paired".
3. Open a game and press play. Hold the mic button: "Alexa, ask replay court to clip that".
   The TV shows a toast, and a "Your clip" notch appears on the timeline.
4. "Alexa, ask replay court to export a highlight reel". The phone QR panel opens on the
   reel. Scan it, and the phone shows the reel when the hfbox runner has rendered it.

If the Fire TV Stick doesn't send the phrase to a dev skill (this is untested,
docs/alexa-research.md §1c), use an Echo or the Alexa phone app on the same account. The
pairing and commands work the same way.

## 6. Demo runbook

- Before going on stage: deploy done, SSM set, Development testing on. The TV is paired
  (the pairing persists in S3; re-pair only if the skill is disabled and re-enabled, which
  changes the userId). The hfbox runner is up (`tmux ls` shows `replay-runner`), so the reel
  renders. Run one `clip that` in the simulator to warm the Lambda.
- On stage: play the game, then say "Alexa, ask replay court to clip that", then "... export
  a highlight reel". Expect about 2–4 s from the end of speech to the TV reacting (Alexa
  speech handling, plus at most one 1 s poll).
- If voice does not answer within about 5 s, say so and use the labelled fallback (§8). Do
  not play recorded audio. The simulator run is backup evidence, and it must be labelled
  as the simulator.

## 7. TV contract (for the TV agent)

All routes take the TV's existing `X-Replay-Key`. One TV per API key: a new pairing
replaces the old one. State has short TTLs: a code lasts 300 s, commands 60 s, and a
heartbeat counts as "watching" for 30 s.

### Routes

- `POST /tv/pair` (no body) -> `{"code": "4829", "expires_at": <unix s>, "paired": bool}`.
  `code` is always 4 digits, 1000–9999, and single-use. A new call voids the previous code.
  `paired` says whether some Alexa user is already linked to this TV. After 5 wrong spoken
  codes, the code is void and the TV must mint a new one.
- `POST /tv/state` `{"game_id": "g_…" | null, "t": <seconds, ≥ 0>, "playing": bool}` ->
  `{"ok": true}`. `game_id` must match `^g_[0-9a-f]+$` or be null (422 otherwise). The
  server extrapolates `t` by the elapsed time while `playing` is true, so the clip lands
  where the user spoke.
- `GET /tv/commands?after=<cursor>` ->
  `{"commands": [Command...], "cursor": "<id or the after you sent>", "paired": bool}`.
  Returns only commands newer than `after`, not acked, and at most 60 s old (by server
  clock), oldest first. Start with `after` empty. Then always send back the `cursor` from
  the last response.
- `POST /tv/commands/{id}/ack` -> `{"id", "acked": true}`. Idempotent. Returns 404 for a
  malformed id. An acked command is never returned again, even with an empty cursor (for
  example after an app restart).

`Command`:

```json
{
  "id": "c_1761091234567ab12",
  "kind": "paired" | "clip_that" | "export_reel",
  "game_id": "g_…" | null,
  "t": 754.2 | null,
  "created_at": 1761091234.567,
  "source": "alexa",
  "reel": {"id": "r_…", "status": "queued" | "running" | "done"} | null
}
```

`reel` is present only on `export_reel`. It is null when the server could not queue the
render (the phone page queues it instead). Ids sort by time. Treat unknown kinds as no-ops
and ack them.

### When to call them

- **Poll** `GET /tv/commands` every **1 s** while Home, Watch or the Pair with Alexa panel
  is in front and the app is foregrounded. Stop when the app is backgrounded. Keep the
  cursor and a set of handled ids in memory. Handle each new command once, then ack it,
  even if handling failed (show the error instead).
- **Heartbeat** `POST /tv/state` every **5 s** while Watch is open, and right away on play,
  pause and seek end. Send `{"game_id": null}` when leaving Watch. Without a heartbeat
  younger than 30 s, Alexa answers "Open a game on your TV first".
- **Pairing UI**: add a "Pair with Alexa" row in Settings. It shows "Paired" when `paired`.
  Selecting it calls `POST /tv/pair` and shows a panel with the code large and spaced
  ("4 8 2 9"). The panel says: `Say: "Alexa, ask replay court to pair code 4 8 2 9"`, with
  a countdown to `expires_at` that re-mints on expiry and a "New code" button. While the
  panel is open, poll; on a `paired` command, toast "Alexa paired" and close the panel.

### What the TV does per command

- `paired`: toast "Alexa paired".
- `clip_that`: `POST /games/{game_id}/triggers {"t": t}`. Clamp `t` to the video duration.
  This is the existing phone tap route. It makes a trigger and its clip, and
  `GET /moments` then lists it as a `bookmark` moment "Your clip". On success, toast
  "Clipped m:ss (Alexa)" and reload moments, so the notch appears. If the game is not the
  one on screen, still clip it and name the game in the toast. On error, toast "Couldn't
  clip that".
- `export_reel`: open that game's player if it isn't already open. Then open the On your
  phone panel (`PhonePanel`) on a new **`reel`** job: `POST /games/{id}/phone-link
{"job": "reel"}`, which the API already accepts. Suggested copy: title "Your highlight
  reel", body "Scan to get it on your phone. It's being made now." The phone page POSTs
  the same reel (same id, 200) and polls it until it is done. Optionally show the status
  under the QR from `GET /games/{id}/exports/reel/{reel.id}`.

## 8. The honest fallback (no voice)

A long press on Select in the player (`longSelect`, which today maps to plain `select` in
`platform/keys.native.ts`) opens a two-item chooser labelled **"Alexa unavailable: using
remote"**, with "Clip that" and "Export highlight reel". Each item builds the same
`Command` object locally (`source: "remote"`, `t` = the player's current time) and passes it
to the same handler the poller uses. The reaction on screen is identical, and the label
says it came from the remote. The phone page `/p/{id}?job=reel` is a third trigger. Never
play pre-recorded audio.

## 9. Security and limits

- `/alexa` has no `X-Replay-Key`. Each request is checked (`replay_api/alexa_verify.py`):
  - the `SignatureCertChainUrl` rules (https, `s3.amazonaws.com`, port 443, path
    `/echo.api/` after `..` normalisation);
  - the PEM chain, using `cryptography`'s web-PKI verifier: valid now, SAN
    `echo-api.amazon.com`, chained to a certifi root;
  - `Signature-256`, an RSA-SHA256 signature of the raw body;
  - `request.timestamp` within 150 s;
  - the skill id equal to `/replay/alexa-skill-id`.

  Any failure gets a 400. Amazon's real chains (echo-api-cert-9 to -12) were checked
  against this verifier and pass at their validity dates.

- Only the paired Alexa `userId` can send commands. Pairing needs the code currently on
  the TV, with 5 tries per code. Only signed requests for our dev skill reach the code
  check at all.
- No secrets in logs. Logs carry the intent name and the reject reason, never the userId.
- Cost: a 1 s poll is 1 Lambda request and 3 small S3 GETs per second while the TV is on
  Home or Watch. That is about $0.004 per hour of S3. An evening is well inside the Lambda
  free tier.
- Last write wins across Lambda instances: one user, a few writes a minute. Two
  simultaneous commands from two Echo devices could drop one.
- Endpoint fallback: if the console rejects the Function URL on save, the documented way
  is a Lambda ARN endpoint. That means a thin us-east-1 Lambda with an Alexa Skills Kit
  trigger (skill id condition) that forwards the event to `/alexa`. It is not built,
  because the Function URL serves a public Amazon wildcard certificate, which is what the
  "wildcard" option expects.
