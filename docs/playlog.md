# Play logs: your own account of a game

A play log is a list of timestamped plays written by a person, not detected by Replay. One
format (`replay.playlog.v1`, `courtcam/courtcam/playlog.py`) serves two uses that are
never mixed with each other or with pipeline output (D-90):

| `use`        | Written by                        | Where it goes                        | Shown in the app?                           |
| ------------ | --------------------------------- | ------------------------------------ | ------------------------------------------- |
| `notes`      | the uploader                      | the game's `notes.json`              | yes, as **"Your note: …"** moments          |
| `evaluation` | whoever hand-checks a clip for us | `samples/truth/<clip>.json` (in git) | never; it is the truth `eval-events` scores |

Pipeline output (`events.json`, `score.json`, `stats`, `hype.json`) is never edited from a
play log. A note that says "Sam made a three" does not add 3 points to the score. To
change the score, use the score correction (`POST /games/{id}/score`).

## Format

CSV with a header row, or the same rows as JSON. Lines starting with `#` are skipped.

```csv
t,team,player,type,result,points,note
0:12.5,red,Sam,shot,make,2,pull-up from the elbow
0:20,blue,Alex,rebound,,,
1:02,,,free throw,miss,,
1:30,,,note,,,great hustle play
```

| column   | required | meaning                                                                                                                |
| -------- | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| `t`      | yes      | when, from the start of the video: seconds (`72.5`) or `m:ss(.s)` (`1:12.5`)                                           |
| `type`   | yes      | `shot`, `free_throw` (or `free throw`), `rebound`, `steal`, `turnover`, `block`, `assist`, `foul`, `highlight`, `note` |
| `team`   | no       | the team as you call it (`red`, `home`, `Wildcats`)                                                                    |
| `player` | no       | a name or number as you call them                                                                                      |
| `result` | shots    | `make` or `miss`                                                                                                       |
| `points` | no       | what a make was worth; a free throw defaults to 1                                                                      |
| `note`   | no       | free text; for a `note` row it is the label shown                                                                      |

Other columns are kept as extras. A bad row is refused with its line number
(`play log line 3: bad time 'soon': use seconds or m:ss`).

JSON is either a bare list of rows (same keys; `made: true/false` may replace `result`) or a
whole document:

```json
{
  "schema": "replay.playlog.v1",
  "use": "notes",
  "entries": [
    {
      "t": 12.5,
      "type": "shot",
      "team": "red",
      "player": "Sam",
      "made": true,
      "points": 2
    }
  ]
}
```

An evaluation document adds the things a scorer needs (see `samples/truth/nottingham_q1.json`):

- `t_rim`: when the ball reached the rim; matching uses it.
- `hoop`: which basket.
- `counts: false` for a shot that does not count, such as one after the whistle. Detecting it is neither right nor wrong.
- `confidence`.
- `clip` with the file, duration and CC attribution.
- `teams`.
- `scoreboard`: score readings over time from an independent source, such as the arena board.

## Import your notes (CLI)

```sh
courtcam notes -o data/games/<game_id> --from my_game.csv
# -> data/games/<game_id>/notes.json (12 notes)
```

`notes.json` is always stored as `use: notes`, `label: "Your notes"`, `source: user`. The
API's `GET /games/{id}/moments` lists each entry as a moment:

- `kind: bookmark`, `source: user`, `trigger: note`;
- label `Your note: <note>`, or `Your note: Sam made shot` when there is no note text;
- id `note1`, `note2`, …

On the TV they sit under "Your bookmarks", next to your clips. A file that says
`use: evaluation` in a game directory is ignored.

## Upload your notes (API)

`POST /games/{id}/notes` takes the same CSV or JSON as the request body and stores it as
the game's `notes.json`. Each upload replaces the earlier notes. It needs the API key
(`X-Replay-Key`); a phone upload token is not enough.

```sh
curl -X POST "$API/games/<game_id>/notes" -H "X-Replay-Key: $KEY" \
  -H "Content-Type: text/csv" --data-binary @my_game.csv
# -> {"notes": 12, "label": "Your notes"}
curl "$API/games/<game_id>/notes" -H "X-Replay-Key: $KEY"   # the notes as stored
```

The route refuses these:

- a body over 1 MB (413);
- a row it cannot read: the error names the line (400);
- a log that says `use: evaluation` (400, "only notes can be loaded");
- a `t` past the end of the video (400).

The notes only ever show as "Your note" moments. Events, score, stats and plays stay as
detected (D-90, D-92).

## Score a game against a hand annotation

```sh
courtcam eval-events -o data/games/<game_id> --truth samples/truth/nottingham_q1.json [--json]
```

What it reports:

- Shots: precision and recall within 1.5 s (`--tol-s`), mean time error, free throws found.
- Make/miss: accuracy, and make precision and recall.
- Points on made shots.
- Team agreement under the better team mapping.
- Final-score error.
- Highlights: precision@5 (`--top-k`), and made field goals inside the top 5.

The numbers for the Nottingham clips and the 3x3 proxy are in docs/decisions.md D-90.
Hand annotations in `samples/truth/` hold facts read from CC BY videos plus their
attribution, never frames.

## Pickup scoring

A sport profile's `scoring:` block sets what a basket is worth and when a game ends:

```yaml
scoring: { inside: 1, outside: 2, to: 11 } # 1s and 2s, game to 11
```

`win_by` defaults to 1. With `to`, the running score restarts at 0-0 after the basket
that wins a game.
