# M10 evidence: profiles, cross-game links, player cards, opt-in face enrollment

**Cards, profiles and reels are synthetic** (labelled "synthetic data" on every card PNG): four `courtcam.synth` games with
ground-truth events, copied from the plays agent's `_eval/out/` (`basketball_half_s7_gt`, `basketball_half_s11_gt`,
`badminton_doubles_s7_gt`, `badminton_doubles_s11_gt`) as `g_bb1`, `g_bb2`, `g_bd1`, `g_bd2`. **Face metrics are on
Creative-Commons footage** (CC BY 3.0, `docs/test-data.md` §3; attribution below). No real-footage (`samples/real`) face was
used anywhere. Synthetic mannequins have no faces, so they cannot test face matching (measured below: 0 usable faces).

Everything was run on hfbox. Box copy `d=/workspace/wt/replay-profiles`,
`PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render`,
`REPLAY_FACE_MODELS=/workspace/wt/replay-env/models/face` (YuNet + SFace, docs/licenses.md). `make_evidence.py` holds every command:

```
python make_evidence.py games /workspace/wt/replay-plays/_eval/out $d/data_m10 \
    bb1=basketball_half_s7_gt bb2=basketball_half_s11_gt bd1=badminton_doubles_s7_gt bd2=badminton_doubles_s11_gt
python make_evidence.py cards $d/data_m10 out/                     # template titles
REPLAY_LLM_URL=http://127.0.0.1:18081 python make_evidence.py cards $d/data_m10 out_llm/ --llm   # Qwen3-4B paraphrase
flock gpu.lock python make_evidence.py faceyield face_yield.json <5 CC clips>          # + face_yield_synthetic.json
flock gpu.lock python make_evidence.py facematch out.json <clip> --dur 120 --dump sheets/ --cache c.npz
python make_evidence.py facematch out.json <clip> --dur 120 --cache c.npz [--labels labels.json]
flock gpu.lock python make_evidence.py gamematch out.json <fisheye clip> --dur 60 --dump strips/
```

## Files

| file | what |
|---|---|
| `profile_{alex,sam,jordan}.json` | `GET /profiles/{id}`: links, `stats_by_sport` (`stats` = shown, `auto`, `edited`, per-game rows), `user_edited_fields` |
| `card_{alex,sam,jordan}.json` / `.png` | `POST /profiles/{id}/card`: card JSON (grounded title + its check report, stat tiles, best moment) and the 810x1080 PNG |
| `reel_{alex,sam,jordan}.json` | `GET /profiles/{id}/reel`: the player's plays across games, game order, with hype, points and clip ids |
| `cards_report.json`, `cards_report_llm.json` | per profile: title, grounding, LLM attempt, JSON determinism (card built twice), reel size, suggestions |
| `face_yield.json`, `face_yield_synthetic.json` | share of detected people whose face is wide enough to embed (CC clips; synthetic games) |
| `face_match_labelled_badminton_fisheye_netpost.json` | enrollment / match metrics with hand-labelled identities |
| `face_match_pseudo_*.json` | the same with ByteTrack track ids as identities (no hand labels; see caveat) |
| `face_gamematch_badminton_fisheye_netpost.json` | end to end through `faces.match_game` (the `face_match` stage / API job) |

## Profiles, links, stats, cards (synthetic)

- "Alex" links the top scorer of `g_bb1` and `g_bb2`; "Sam" the most-moving player of `g_bd1` and `g_bd2`; "Jordan" one
  basketball and one badminton player (two sports). Linking wrote the name and `profile_id` onto each game's roster.
- Stats across two games each, e.g. Alex: 6 points, 3/6 FG (twos 3/5, threes 0/1), 139 m, per-game rows 4 + 2 points; Sam:
  14 rallies, 26 contacts, 2 serves, 141.6 m. `rallies_won` is absent on purpose: the synthetic rallies carry no
  `winner_side`, so it is unknown rather than 0.
- User correction: Alex `rebounds` 0 → 4. The profile shows 4, keeps `auto.rebounds = 0`, lists `edited: ["rebounds"]` and
  `user_edited_fields: ["positions", "stats_by_sport.basketball.rebounds"]`; the card tile says EDITED.
- Titles (template path): "Alex the scorer: 6 points in 2 games", "Sam the rally machine: 14 rallies in 2 games",
  "Jordan the rally machine: 3 rallies in 1 game"; all three pass `narrate.grounding.check` (3/3). Card JSON built twice:
  byte-identical 3/3. API wall time per profile (link ×2, card render, reel, suggestions): 0.5–1.1 s.
- LLM paraphrase (llama.cpp, Qwen3-4B-Instruct Q4_K_M, temperature 0): 3/3 accepted by the grounding check ("Alex scores 6
  in 2 games", "Sam: 14 rallies in 2 games", "Jordan: 3 rallies in 1 game"). A test forces an ungrounded template (a user-entered 3-pt total the events cannot
  vouch for) and checks that the title falls back to the next grounded template.
- Suggestions without face enrollment are same-name only: Jordan got 1 (an unlinked roster player already named "Jordan"
  in the synthetic games).

## Faces: how many court players even yield a usable face

`faceyield`: YOLO11m person boxes (imgsz 1280) every 2 s over each 240 s clip, YuNet on the head region of each box
(upscaled to 320 px), "usable" = a detected face ≥ 24 px wide in source pixels (the size below which `providers/face.py`
does not embed). People include spectators, line judges and neighbouring courts.

| clip (CC BY) | person boxes | face detected | usable (≥ 24 px) | face width p10 / p50 / p90 (px) |
|---|---|---|---|---|
| basketball_nottingham_widecam q1 | 3628 | 32.6 % | **3.5 %** | 5.2 / 6.7 / 24.8 |
| pickleball_surrey2026 | 1677 | 39.8 % | **6.0 %** | 10.9 / 14.9 / 29.0 |
| pickleball_surrey2022 | 2427 | 60.7 % | **4.5 %** | 12.2 / 17.4 / 23.3 |
| badminton_usnationals2012 | 2256 | 74.7 % | **2.8 %** | 8.5 / 11.3 / 19.7 |
| badminton_fisheye_netpost | 802 | 26.1 % | **14.8 %** | 18.8 / 25.2 / 42.4 |
| synthetic g_bb1 / g_bd1 (mannequins) | 224 / 224 | 34.8 % / 6.2 % | **0 % / 0 %** | 4.3–8.0 / 9.9–11.5 |

The "detected" faces on mannequins are YuNet false positives on blank heads, all under 12 px, so none is embedded.
(`face_yield.json` also has a `wide.mp4` row from the same run whose key collided between the two synthetic games;
`face_yield_synthetic.json` is the rerun with both.) Takeaway: from a phone on a tripod, only near-camera players have
identifiable faces, a few percent of samples; face matching can only ever be a suggestion source for those, never the
linking path.

## Faces: enrollment and matching on CC footage

`facematch`: YOLO11m + ByteTrack over 0–120 s at 15 fps, faces embedded every 3rd tracked frame (5 fps). A person is enrolled
from their first 3 usable faces (stand-in for "their own photos"); every later face (≥ 2 s after enrollment) is a genuine
probe; every face of everyone not enrolled is an unenrolled probe, compared against the enrolled embeddings only. Two folds
(each person enrolled once, unenrolled once). "Windows" apply the game matcher's decision (`faces.decide`: one enrolled
profile wins ≥ 2 votes AND ≥ half of the samples with a usable face) to consecutive groups of 12 usable faces, i.e. one
game's worth of samples per player.

**Hand-labelled** (`badminton_fisheye_netpost`: 2 players, 13 tracks with a usable face, 577 faces; tracks sorted into
person A / person B / not-a-face by eye from per-track contact sheets that were deleted afterwards):

| cosine threshold | genuine faces matched (A / B) | wrong profile | unenrolled faces matched (A / B fold) | genuine windows suggested | unenrolled windows suggested |
|---|---|---|---|---|---|
| 0.363 (OpenCV's SFace point) | 77.2 % / 84.2 % | 0 | 21.6 % / 18.2 % | 45 / 45 | **2 / 47** |
| **0.45 (default)** | 63.5 % / 72.4 % | 0 | 3.5 % / 2.9 % | 39 / 45 | **0 / 47** |
| 0.5 | 52.0 % / 67.4 % | 0 | 0.9 % / 0.9 % | 33 / 45 | 0 / 47 |
| 0.6 | 21.0 % / 51.6 % | 0 | 0 % / 0 % | 11 / 45 | 0 / 47 |

Genuine similarity p10/p50/p90: 0.13/0.51/0.64 (A), 0.31/0.60/0.73 (B); best unenrolled similarity p50/p90/p99 ≈
0.28/0.40/0.49. The 0.45 default and the majority rule were chosen on this clip (privacy first: no unenrolled window
suggested), so this is the tuning set, not a held-out test.

**Pseudo-labels** (track id = identity) on the other clips; an id switch or a fragmented person turns genuine matches into
"unenrolled" ones, so unenrolled numbers are upper bounds and genuine numbers lower bounds. On the fisheye clip the same
data scored 16/45 unenrolled windows suggested with pseudo-labels against 0/47 with hand labels, which is how large that
bias is. At 0.45 (sum over two folds):

| clip | people (tracks) with ≥ 6 faces over ≥ 4 s | genuine windows suggested right | unenrolled windows suggested (upper bound) |
|---|---|---|---|
| pickleball_surrey2026 (563 faces) | 9 | 4 / 36 | 5 / 40 (0.5: 2 / 40) |
| badminton_usnationals2012 (249 faces) | 9 | 5 / 9 | 3 / 13 (0.5: 0 / 13) |

The pickleball and US-nationals tracks could not be hand-labelled reliably (caps, sunglasses, profile views, frequent id
switches in the contact sheets), so no clean accuracy number exists for them; genuine matching there is clearly weak.

**End to end** (`gamematch`, the product path `faces.match_game`): fisheye clip 0–60 s, YOLO+ByteTrack tracks written as a
game, the longest track's head crops from 0–10 s enrolled (9 photos, 8 faces), matching run on the tracks after 10 s only:
48 tracked players checked, 208 samples, 48 with a usable face, 11.3 s. Suggestions: `t1` (10 of 12 votes, max similarity
0.70) and `t68` (10/12, 0.75); an eye check of both strips shows the enrolled player (t68 is his later track). No other
player, including his opponent, was suggested.

Nothing from the face runs was kept beyond the counts in these JSON files: crops, contact sheets, embeddings caches and the
temporary enrollment store were deleted on the box and locally.

## Attribution (CC BY 3.0, https://creativecommons.org/licenses/by/3.0/; segments cut to 240 s, otherwise unmodified)

- "Badminton recorded with fisheye lens (Hans & René)" by bvconquesto, https://www.youtube.com/watch?v=B9XLUHQfh4A
- "2026.09.04 MD4.0 (age 50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)" by pickleball4you,
  https://www.youtube.com/watch?v=4M58YJoZ4O4
- "2022.05.07 MXD 3.5-4.0 Bronze Medal Game" by pickleball4you, https://www.youtube.com/watch?v=wY_KUvQ8w7I
- "2012 US Badminton Adult National Championships Mixed Doubles Quarter Finals HD 1080P" by Roy Huang,
  https://www.youtube.com/watch?v=654WkfWSYf0
- "25th October 2015 - Nottingham Wildcats vs Barking Abbey Crusaders wide angle cam view only" by Super League Basketball
  (video (c) Peter Kaloczy), https://www.youtube.com/watch?v=aH6PRcV4DHE
