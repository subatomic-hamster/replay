# M10 UI evidence: player profiles on the TV and the phone, and the one-row Watch menu

These are 1080p screenshots of the react-native-tvos app (its react-native-web build),
produced by `apps/tv/e2e-evidence/M10-ui.spec.ts`. The phone pages were captured at
430x932 by `apps/web/e2e/S-52-phone-profiles.spec.ts`. Every frame here is
**synthetic**. No frame comes from `samples/real/`, and no real person's face or photo
appears.

## `tv-synthetic-live/`: the real API on synthetic games

`services/api` (uvicorn, `REPLAY_PIPELINE=fake`) serves a data dir built from synthetic
ground-truth renders. `docs/evidence/M10/make_evidence.py games` copied them from the
plays agent's `_eval/out/` as `g_bb1` (`basketball_half_s7_gt`), `g_bb2`
(`basketball_half_s11_gt`) and `g_bd1` (`badminton_doubles_s7_gt`).

`make_evidence.py cards` then created the profiles through the API:

- **Alex**: the top scorer of each basketball game, plus a user correction (rebounds 4).
- **Sam**: one badminton player.
- **Jordan**: two sports.

One more step makes the links screen show a suggestion: roster player `g_bb2/p3` was
tagged "Jordan" (`PATCH /games/g_bb2/players/p3`), so Jordan's Links tab offers it as a
same-name suggestion.

The synthetic mannequins have no faces, so there are no face suggestions in this run (see
`docs/evidence/M10/README.md` for the measured face yield). The mock run shows the face
suggestion screen instead.

During the run the spec itself:

- corrects one stat with the D-pad (`PATCH /profiles/{id}`, shots 03–04);
- renders the card PNG (`POST /profiles/{id}/card`, shot 05);
- plays the career reel (shot 06).

## `tv-mock/`: the mock fixture

The same spec runs against `packages/tv-core/src/mock.ts`, which holds synthetic profiles:

- **Marcus**: linked in two games.
- **Jordan**: opted into face enrollment, and has a face suggestion.
- **Sam**: not enrolled.

The card image is a hand-drawn SVG labelled "MOCK CARD · SYNTHETIC".

## `phone-mock/`: the phone companion (mock)

| File | Screen |
| --- | --- |
| phone-01 | The profile list and the create form. |
| phone-02 | Profile edit after save and a photo upload (a synthetic 1x1 PNG). |
| phone-03 | The face consent step: what is stored (one embedding, photos deleted), that only enrolled people are matched, and how to delete it. The photo picker and the button stay disabled until the box is ticked. |
| phone-04 | After enrolling (mock): the "Delete my face data" control. |

## TV screens

| File | Screen |
| --- | --- |
| 01 | Players: one card per profile (initials or photo, sports, linked games). Reached from the Library with Up → Players. |
| 02 | Profile → Stats: per-sport career stats, labelled auto-detected. A correction is flagged EDITED with the auto value beside it. |
| 03 | A stat in D-pad edit mode (◀ value ▶). |
| 04 | Saved: the row is flagged EDITED · auto N. |
| 05 | Card: the API's PNG next to its JSON fields (title, tiles, EDITED tags, best moment). |
| 06 | Reel: the player's plays across games, played in order with a PLAY i / N counter. |
| 07 | Links of the first profile. |
| 08 | Links of a second profile. Suggestions are labelled as needing confirmation (live: a same-name suggestion; mock: a face suggestion marked opt-in). |
| 09 | The Watch menu is one row at 1080p. Before, 16+ items wrapped into two rows over the video. |
| 10 | The "Players ▸" group, open in place of the top row. |
| 11 | Link profile on a picked player: the profile picker. |

## How to reproduce (on the box)

```sh
d=<repo copy>; source /workspace/wt/replay-env/env.sh
export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render
cd $d/docs/evidence/M10
python make_evidence.py games /workspace/wt/replay-plays/_eval/out $d/data_m10ui \
    bb1=basketball_half_s7_gt bb2=basketball_half_s11_gt bd1=badminton_doubles_s7_gt
python make_evidence.py cards $d/data_m10ui /tmp/cards
REPLAY_PIPELINE=fake REPLAY_DATA_DIR=$d/data_m10ui python -m uvicorn replay_api.main:app --port 8021 &
curl -X PATCH -H 'content-type: application/json' -d '{"name":"Jordan"}' localhost:8021/games/g_bb2/players/p3

cd $d/apps/tv
REPLAY_TV_API=http://localhost:8021 REPLAY_TV_EVIDENCE_DIR=$d/docs/evidence/M10-ui/tv-synthetic-live \
  pnpm exec playwright test --project=evidence e2e-evidence/M10-ui
REPLAY_TV_API=mock REPLAY_TV_EVIDENCE_DIR=$d/docs/evidence/M10-ui/tv-mock \
  pnpm exec playwright test --project=evidence e2e-evidence/M10-ui
cd $d/apps/web
REPLAY_WEB_EVIDENCE_DIR=$d/docs/evidence/M10-ui/phone-mock \
  pnpm exec playwright test --project=chromium e2e/S-52
```
