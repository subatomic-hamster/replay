# Replay handoff (2026-10-22, about 22:00 UTC)

Written for the next agent, who will pick up this project in a different directory. It
covers where the project stands, what is not in git, the rules the owner set, how to
build, test, deploy and check on the device, and what to do next. Read it top to bottom
once. After that, use §5–§7 as a runbook.

**Deadline:** Amazon Developer Hackathon (Fire TV track, plus AWS Builder and Open Source
mini challenges). Submissions close **2026-10-23**; check the exact time on Devpost.

---

## 1. What Replay is

You put one phone on a tripod to film an amateur court-sports game (basketball first;
volleyball, pickleball and badminton through sport profiles). Replay turns that video
into a broadcast-like game on Fire TV. With the remote you can:

- follow any player;
- turn on broadcast mode with a score bug, replays and commentary;
- clip the play that just ended ("Replay, clip that" by tap, gesture or voice);
- switch between replay angles (real video, 2.5D, virtual 3D);
- browse highlights and stats.

A phone companion handles upload, calibration, naming players, review and search.

- Product overview, architecture diagram and licence notes: `README.md`. **Part of its
  status table is stale; see §8.**
- Full spec: `REPLAY_PLAN.md`. It is **gitignored**, so copy it by hand (§3).
- Decision log: `docs/decisions.md` (D-1 … D-96). Read it before changing architecture.
- Milestone log with measured numbers: `docs/progress.md`. Overnight report:
  `docs/OVERNIGHT_REPORT.md`.

## 2. State at handoff

- Branch `main` at the handoff commit. The tree is clean.
- **Not pushed:** `origin` (`git@github.com:subatomic-hamster/replay.git`) is 135+ commits
  behind. Pushing is the owner's call.
- The last code commit, `ed48534`, passed the full gate (`ALL GREEN`): 133 TV e2e, 125 web
  e2e, plus every pytest suite and lint.

### What is live

| Piece                                            | Where                                                                | State                                                                                                                                                   |
| ------------------------------------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API (Lambda Function URL)                        | https://a3pd2rqlfcehgeg4dn2gbswnqa0dozxj.lambda-url.us-east-1.on.aws | Deployed 2026-10-22 14:35 UTC. API code is unchanged since then.                                                                                        |
| Web (phone companion) and TV web build           | https://d2454ty37m7cp7.cloudfront.net (TV at `/tvapp/`)              | **Stale.** It is the 14:35 UTC build. The UI commits 59a7753 … ed48534 are not live yet. The artifacts are built (§5); the owner has to run the deploy. |
| hfbox runner (pulls jobs, runs the GPU pipeline) | tmux `replay-runner` on hfbox, code in `/workspace/wt/replay-deploy` | Running. Code is at 59a7753, which is current for the pipeline.                                                                                         |
| Demo game                                        | `g_c8b6186280ac` (Nottingham vs Barking Abbey, CC BY, 241 s)         | Re-processed at 17:19 UTC with the current pipeline.                                                                                                    |
| Fire TV Stick APK                                | Owner's Stick (AFTSS, USB adb serial `G4N1CQ1845221A3T`)             | Built from `ed48534` and installed.                                                                                                                     |

### Recent work (newest first; all gated)

- `ed48534`: plain words and honest states on the leftover screens. Covers the
  processing chip, the "game is gone" screen, clip sources, phone stage names, the sport
  picker, profile rows, expired links, Settings focus and the Commentary toast.
- `481659a`: opening a game from its Home card always plays from the saved spot.
- `e27af84`: play and pause icons (state icon, "▶ Paused", centred flash).
- `59a7753`: UI pass for one remote grammar:
  - Menu always opens Do more; Back goes up one level; Home asks for a second Back
    before exiting.
  - Do more has six tiles.
  - Moments filter by All/Scores/Bookmarks.
  - A context chip and a 3-key legend appear on every screen.
  - Labels say "Camera" / "Virtual replay".
- `dff202f`: virtual-angle fixes (no grey blob, near-camera people and ball culled).

The UI spec and audit for this pass were in the old session's scratchpad and are gone.
The commits and the e2e specs (`apps/tv/e2e/TV-*.spec.ts`, `apps/web/e2e/S-*.spec.ts`)
are the record.

### Verified on the Stick before its network broke

- Home legend; the six-tile Do more; Moments.
- Replay angles breadcrumb and "Camera 3 of 9".
- Back twice exits to Home.
- Pause shows "▶ Paused 0:43".
- Settings opens on its first row.
- The Play/Pause remote key works.

### Not yet verified on the Stick

- The burned-in "VIRTUAL REPLAY | Broadcast high" label on a virtual angle.
- The Commentary on/off toast.
- The processing chip.
- The Players screen. The live API has no profiles; the web build was checked.

## 3. What is NOT in git (and how to get it)

A fresh clone lacks these:

| Item                             | Location (owner's laptop unless noted)                                                                | Notes                                                                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPLAY_PLAN.md`                 | repo root, gitignored                                                                                 | Full spec. Copy it alongside the clone.                                                                                                      |
| Real footage                     | `samples/real/*.mp4` etc., gitignored. Shared copy on hfbox: `/workspace/wt/replay-env/samples-real/` | YouTube-licensed. **Local only (D-7).** The volleyball game has minors (**D-76**): never commit or upload it, its frames or its screenshots. |
| CC BY clips                      | hfbox `/workspace/wt/replay-env/samples-cc/`                                                          | Attribution is in `docs/test-data.md`.                                                                                                       |
| `data/`                          | repo root, gitignored                                                                                 | Local game data and caches. Regenerated by the pipeline.                                                                                     |
| `docs/evidence/local/`           | gitignored                                                                                            | Evidence rendered from real footage. Never ships.                                                                                            |
| `infra/build/`, `infra/cdk.out/` | laptop repo copy                                                                                      | The **current deploy artifacts** for ed48534. Copy these too, or rebuild them (§5).                                                          |
| API and worker keys              | hfbox `/workspace/wt/replay-env/{api-key,worker-key}` (0600)                                          | Never print, log or commit them. The APK embeds the API key, so never commit or upload the APK.                                              |
| `yolo11n.pt`                     | repo root, gitignored (`*.pt`)                                                                        | Auto-downloaded by ultralytics.                                                                                                              |
| Agent memory                     | `~/.claude/projects/-home-sdash-Documents-projects-hackathon-projects-firestick-replay/memory/`       | Notes the old agent kept. Everything in them that still matters is folded into this file.                                                    |

To move the laptop state as is, copy the whole directory, not a clone:
`rsync -a --exclude node_modules --exclude .venv <old>/ <new>/`.

If you clone instead, copy `REPLAY_PLAN.md`, `infra/build`, `infra/cdk.out` and
`samples/real` across by hand. Never move real footage anywhere but the owner's machines
and hfbox.

## 4. Rules from the owner (non-negotiable)

Verbatim intent:

- "No faked outputs. No mock data presented as real, no hard-coded results, and no
  hand-edited JSON passed off as pipeline output. Synthetic data is always labeled
  synthetic."
- "No copyrighted footage, music, or trademarks in commits or demo assets. Real footage
  stays out of git."
- "Respect licenses: courtcam stays MIT-clean; research-licensed weights and models are
  optional extras documented in docs/licenses.md."
- "Privacy: face matching and voice identification only for enrolled, consenting users;
  unenrolled people stay anonymous."
- "No secrets in the repo. Configuration comes from environment variables."
- "Commit early and often…; never leave main broken."
- "Spend money only where hfbox usage is already authorized. Don't sign up for paid
  services."

Ways of working the owner asked for:

- **Orchestration.** The main agent coordinates. Subagents do the work, about 4 at once
  at most, each owning disjoint files. Opus handles code; Sonnet handles research and
  menial work. **Subagents never run git**; the main agent commits.
- **Commit format.** One line `<feat|fix|chore>: message`, a blank line, then the
  session trailer the harness gives you. Commit only after the gate is ALL GREEN (§5).
- **Testing.** After each feature, run a Playwright check. Accept features on **real
  games** (basketball and volleyball), not synthetic clips. Synthetic fixtures are fine
  for fast CI, labelled synthetic.
- **Native first.** Where web and native trade off, pick what is best for the eventual
  native Fire TV app. The web build is the test and demo surface.
- **Plain words in the UI.** The users are non-technical parents. Labels must be honest;
  no debug readouts.
- **File edits.** Edit repo files with the editor tools only: no `sed -i`, heredocs or
  `tee` into the repo.
- **Things the owner does, not you.** The old agent's permission requests for these were
  denied; ask the owner instead of working around them:
  - `cdk bootstrap` / `cdk deploy`;
  - `rds create-db-instance`;
  - an EC2 GPU quota increase;
  - an `adb reverse` relay.

## 5. Build, test, gate (all compute runs on hfbox)

**hfbox** (`ssh hfbox`) is a shared AMD RX 9070 XT ROCm box. It is a podman container
with **16 GiB cgroup memory**; `free` shows the host's memory and is misleading. Read
`docs/compute.md` first.

- **All compute runs here:** pytest, tsc, Playwright, the pipeline, ffmpeg, builds. The
  laptop only edits, runs git and does ssh/rsync. If the box is down, wait; don't run
  things locally.
- **Environment:** `source /workspace/wt/replay-env/env.sh` (venv py3.12 with ROCm
  torch, ffmpeg, node 22 + pnpm, Playwright browsers). `READY` in that directory lists
  the apt commands to rerun after a box restart.
- **Locks:**
  - jobs over ~3 GB RAM: `flock /workspace/wt/replay-env/.mem.lock`;
  - heavy CPU: `.cpu.lock`, at most 6 threads;
  - Playwright: `.pw.lock` (it uses fixed ports);
  - GPU: `/workspace/airtools/.gpu.lock`.
  - Do **not** wrap the API or runner in the GPU lock. The worker takes it per stage, so
    an outer lock deadlocks.
- **Shared tmux.** Never `tmux kill-server`. Never `tmux set-environment -g`; pass
  variables with `tmux new -e`. Kill only your own named sessions.
- **Copying code to the box.** Copy git-tracked files only:
  `git ls-files -c -o --exclude-standard -z | rsync -a --from0 --files-from=- ./ hfbox:<dir>/`.
  Exclude `/data/` with the anchored form. Never copy `samples/real` footage or
  `docs/evidence/local` into agent copies.
- **ssh failures.** `ssh hfbox` goes through the box owner's Tailscale Funnel. If it
  fails with "SSL routines::unexpected eof", the box side is down; wait.

**Commit gate.** Run it from a snapshot of the index so you test exactly what you commit:

```sh
S=<your scratch dir>
git add -A
rm -rf $S/idx
git checkout-index -a --prefix=$S/idx/
rsync -a --delete --exclude /data/ --exclude node_modules --exclude .venv --exclude test-results \
  $S/idx/ hfbox:/workspace/wt/replay-orch/
ssh hfbox 'tmux new -d -s replay-gate -e CI=1 "flock /workspace/wt/replay-env/.mem.lock bash /workspace/wt/replay-orch/scripts/box-test.sh /workspace/wt/replay-orch > /workspace/wt/replay-env/gate.log 2>&1; echo exit=\$? >> /workspace/wt/replay-env/gate.log"'
# wait for ^exit= in gate.log (~6 min); require "ALL GREEN" and exit=0
```

**Deploy artifacts and APK.**

1. Copy the snapshot to `hfbox:/workspace/wt/replay-deploy-next/` with these excludes:
   `/data/ node_modules .venv test-results /infra/build/ /infra/cdk.out/ /samples/real
/apps/tv/android/app/build/ /apps/tv/android/build/ .gradle local.properties .cxx`.
2. Run the build in tmux:
   `tmux new -d -s replay-final -e HOME=/root "bash /workspace/wt/replay-env/final-build.sh > /workspace/wt/replay-env/final-build.log 2>&1; echo exit=\$? >> /workspace/wt/replay-env/final-build.log"`.
   A copy of the script is in `scripts/hfbox/final-build.sh`.
3. Pull `infra/build` and `infra/cdk.out` back into the laptop repo.
4. Pull `apps/tv/android/app/build/outputs/apk/release/app-release.apk` to a scratch
   directory, never into the repo.

**Without the box**, see README "Developing without the box":
`VITE_MOCK_API=1 pnpm web` in `apps/tv`, and `REPLAY_PIPELINE=fake` for the API.

## 6. AWS deploy and the runner

- AWS CLI profile **`replay`** (us-east-1, account 342934376025, `aws login --profile
replay`). The profile has no region, so always set `AWS_REGION=us-east-1`. Profile
  `oddski` belongs to a different project; never use it.
- Free plan. Credits (about $160) expire 2027-04-19. Budget `replay-monthly-10usd`.
  Confirm with the owner before creating anything with idle cost.
- **The owner deploys.** From `infra/`, with the artifacts from §5:
  ```sh
  export AWS_REGION=us-east-1 && eval "$(aws configure export-credentials --profile replay --format env)" && npx -y aws-cdk@2.1145.0 deploy --app cdk.out ReplayCloud --outputs-file build/outputs.json
  ```
- Lambda `ReplayCloud-ApiF70053CD-kcGLGKoFfvZS`; log group
  `ReplayCloud-ApiLogs3D05D88B-WULGbccnyUER`; CloudFront distribution `E1HYNF4IXB0RQ4`.
  Design: `docs/aws-migration.md` (D-80) and `docs/aws-deploy.md`.
- **Lambda concurrency limit is 10.** The owner filed a request for 1000. One open
  Watch makes about 9 parallel requests, so 429 throttling is a demo risk (D-87 added
  client retry).
- **EC2 GPU quota is 0.** The GPU work stays on hfbox as a pull-based runner with no AWS
  credentials.

**Runner** (`scripts/hfbox/runner.sh` is a copy of `/workspace/wt/replay-env/runner.sh`).
It has no auto-restart, and a box restart (OOM) kills it. After pipeline or API code
changes:

```sh
# 1. rsync the snapshot to hfbox:/workspace/wt/replay-deploy/ (same excludes as replay-deploy-next)
ssh hfbox 'tmux kill-session -t replay-runner; tmux new -d -s replay-runner "bash /workspace/wt/replay-env/runner.sh"'
# log: /workspace/wt/replay-env/runner.log
```

To re-process a game, run this on hfbox without printing the key:
`curl -X POST -H "X-Replay-Key: $(cat /workspace/wt/replay-env/api-key)" <API>/games/<id>/process`.
It takes about 7 minutes for the 241 s demo game.

## 7. Fire TV Stick

Runbook: `docs/fire-tv.md`.

- The Stick is AFTSS (Fire OS 7, Android 9), USB adb serial `G4N1CQ1845221A3T`, package
  `com.replaytv`.
- **It works headless** (HDMI unplugged):
  1. `adb shell input keyevent KEYCODE_WAKEUP`;
  2. `adb shell am start -n com.replaytv/.MainActivity`;
  3. then key events, `adb exec-out screencap -p` and video playback all work.
- Before sending keys, check that `adb shell dumpsys window | grep mCurrentFocus` names
  `com.replaytv`. If several agents share the device, hold a lock file for the whole
  session.
- Install: `adb install -r app-release.apk`. The API address is baked in at build time;
  Settings in the app can change it.

### Open blocker: the Stick has no usable network

- **GTvisitor:** intercepts HTTPS ("Trust anchor for certification path not found").
- **eduroam:** blocks or intercepts traffic. Ping 8.8.8.8 fails, and Amazon's own
  endpoints fail with "Hostname could not be verified by certificate".
- In both cases the app shows "Replay can't connect – Network request failed". **This is
  not an app bug.**
- **Fix:** the owner's phone hotspot **"Subhams"**. Its password is already saved on the
  Stick, but the Stick never saw it in a scan. The owner needs to keep the hotspot screen
  open, use 2.4 GHz or "Maximize Compatibility", and keep the phone near the Stick. Once
  it is visible, pick it in Settings → Network → See All Networks (it auto-joins).
- Then finish the "Not yet verified on the Stick" list in §2.

## 8. Next steps, in priority order for the deadline

1. **Owner deploys the web build** (§6). The artifacts in `infra/cdk.out` are for
   ed48534. Then open https://d2454ty37m7cp7.cloudfront.net/tvapp/ and check that the
   new UI is live (Do more tiles, legend, Paused label).
2. **Get the Stick onto the hotspot** (§7) and finish the device checks.
3. **Clean the live library.** The "cloud smoke (synthetic)" games and an empty
   Volleyball pending game `g_4770db774635` still lead live Home. Deleting them is the
   owner's call; ask first.
4. **Demo recording.** Script: `docs/demo-script.md` (updated in 59a7753). Beat status:
   `docs/demo-readiness.md`. Its "Morning" checklist items 1–4 and 8 are done; items 5
   (cleanup) and 6 (film and calibrate new demo footage) remain with the owner.
5. **Refresh `README.md`.** Its "Feature status" and "Honest limitations" sections still
   say "No device testing", "Local only. No AWS deployment" and "AWS stubs only". The
   app now runs on a Fire TV Stick against a deployed AWS API (docs/fire-tv.md §0,
   docs/aws-deploy.md). Update the README before submission; judges read it first.
6. **Devpost submission.** Fire TV track, plus AWS Builder and Open Source.
   - `courtcam/` is the MIT open-source piece; `scripts/split-courtcam.sh` splits it out
     (D-36).
   - The YOLO extra is AGPL; see the licence notes in the README.
   - Use only synthetic or CC BY media in the submission. Never use volleyball or
     YouTube footage.
7. **After the demo:** delete hfbox agent work directories under `/workspace/wt/`:
   - `replay-uipass`, `replay-uipass-{a,b,c,d}`, `replay-play`, `replay-ppfix`,
     `replay-fix-tv`, `replay-fix-web`, `replay-deploy-next`;
   - earlier ones: `replay-follow`, `replay-angles`, `replay-angles-data`,
     `replay-score`, `replay-pcard`.
   - `replay-pcard` holds **local-only volleyball data**; delete it.
   - Keep `replay-env`, `replay-deploy` and `replay-orch`.

## 9. Known gaps (not chased)

**Small UI issues:**

- The Replay angles legend has no Select entry, because the legend is capped at 3 keys.
- Reduced motion is not handled.
- The follow ring and the player card can differ in colour on mixed-team tracks.
- Long game titles crowd the angles breadcrumb.
- Possible rare case: after a "can't connect" start, three Lefts then Play/Pause left
  the video playing.

**Accuracy on real footage** (details in `docs/demo-readiness.md` "Routed to other
agents" and D-89 … D-96):

- Identity fragments into many ids on long games.
- Both teams can get the same team label.
- Real shot recall is low.
- There is no basketball block detector (D-96).
- The virtual views show only some of the players.

## 10. Where to look

| Need                                               | File                                                                      |
| -------------------------------------------------- | ------------------------------------------------------------------------- |
| Spec                                               | `REPLAY_PLAN.md` (copy by hand)                                           |
| Why something is the way it is                     | `docs/decisions.md`                                                       |
| Test spec (product-level)                          | `docs/test-spec.md`                                                       |
| Box, locks and throughput                          | `docs/compute.md`                                                         |
| AWS design, deploy, cost, teardown                 | `docs/aws-migration.md`, `docs/aws-deploy.md`, `docs/aws-integrations.md` |
| Fire TV build and side-load                        | `docs/fire-tv.md`                                                         |
| Data contracts (scene package)                     | `docs/scene-format.md`                                                    |
| Models and licences                                | `docs/models.md`, `docs/licenses.md`                                      |
| Footage sources and attribution                    | `docs/test-data.md`                                                       |
| Lessons and gotchas                                | `docs/friction-log.md`                                                    |
| Gate script                                        | `scripts/box-test.sh`                                                     |
| Runner and final build (copies of the box scripts) | `scripts/hfbox/`                                                          |
