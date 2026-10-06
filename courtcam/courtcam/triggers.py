""" "Replay, clip that" (plan §4.4 "Plays", vision "Replay, clip that").

Three trigger sources, one resolution rule:

* **gesture** — arms crossed overhead in an X, held >= `gesture_hold_s`, from the 2D
  keypoints of a tracked player (`poses/`): both wrists above the head and the forearms
  crossed (the wrists sit on the opposite sides of the elbows, or the forearm segments
  intersect). The identity is the track's player id.
* **voice** — ASR over the 16 kHz audio, then a fuzzy match (difflib) of "replay ...
  clip <that | name>" against the roster; the subject is the named player. Who spoke is
  known only through an opt-in voice enrollment (`speaker` callable), never guessed.
* **tap** — from the phone companion through the API (`POST /games/{id}/triggers`).

Resolution: a trigger at T belongs to the play that most recently ended in
[T - max_lag_s, T + early_s]; the clip is that whole play (padded `clip_pad_s`), owned
by the gesture-maker / speaker, else the named subject, and cross-linked to the play's
participants.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from .events import Signals, x_pose
from .profiles import TriggerCfg
from .schema import Attribution, Clip, Play, Trigger

ASR = Callable[[list[np.ndarray], int], list[str]]  # (clips, sr) -> one text per clip
# (samples, sr, t0, t1) -> enrolled player id or None
Speaker = Callable[[np.ndarray, int, float, float], str | None]

CLIP_PAD_S = 1.0
THAT = {"that", "this", "it", "dat"}


# --- gesture ---------------------------------------------------------------------


def detect_gestures(signals: Signals, cfg: TriggerCfg) -> list[Trigger]:
    """One trigger per held X: t_start = first X sample, t = last one."""
    out: list[Trigger] = []
    for pid in sorted(signals.poses):
        ts, kp = signals.kp_px(pid, -np.inf, np.inf)
        hit = x_pose(kp, cfg.gesture_min_kp)
        run: list[float] = []
        for t, h in zip([*ts, np.inf], [*hit, False], strict=True):
            if h and (not run or t - run[-1] <= cfg.gesture_max_gap_s):
                run.append(float(t))
                continue
            if run and run[-1] - run[0] >= cfg.gesture_hold_s - 1e-6:
                held = run[-1] - run[0]
                out.append(
                    Trigger(
                        id="", type="gesture", t_start=round(run[0], 3), t=round(run[-1], 3),
                        by_player_id=pid,
                        confidence=round(min(0.95, 0.2 + 0.3 * held / cfg.gesture_hold_s), 3),
                    )
                )  # fmt: skip
            run = [float(t)] if h else []
    return sorted(out, key=lambda tr: tr.t)


# --- voice -----------------------------------------------------------------------


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def parse_command(
    words: list[str], roster: dict[str, str], cfg: TriggerCfg
) -> tuple[int, int, str | None, float] | None:
    """Find "<wake> [..] <command> <that|name>" in `words` (lowercase tokens).

    Returns (index of the wake word, index of the last word used, subject player id or
    None, score) or None. The wake word may be split by the ASR ("re play")."""
    for i in range(len(words)):
        cand = [(words[i], i)]
        if i + 1 < len(words):
            cand.append((words[i] + words[i + 1], i + 1))
        for w, j in cand:
            s_wake = _ratio(w, cfg.wake)
            if s_wake < cfg.fuzzy:
                continue
            for k in range(j + 1, min(j + 4, len(words))):
                s_cmd = _ratio(words[k], cfg.command)
                if s_cmd < cfg.fuzzy:
                    continue
                rest = words[k + 1 : k + 3]
                subject, s_name, last = None, 1.0, k
                if rest and rest[0] not in THAT:
                    subject, s_name, last = _name(rest, roster, cfg, k + 1)
                elif rest:
                    last = k + 1
                return i, last, subject, round((s_wake + s_cmd + s_name) / 3, 3)
    return None


def _name(rest: list[str], roster: dict[str, str], cfg: TriggerCfg, at: int):
    """Best roster match for the word(s) after the command: (player id, score, last idx)."""
    best = (None, 1.0, at - 1)  # "clip" alone: no subject, still a command
    best_s = cfg.fuzzy
    for name, pid in roster.items():
        parts = tokens(name)
        if not parts:
            continue
        for n in (len(parts), 1):
            said = "".join(rest[:n])
            for target in ("".join(parts), parts[0]):
                s = _ratio(said, target)
                if s >= best_s:
                    best_s, best = s, (pid, s, at + n - 1)
    return best


def detect_voice(
    samples: np.ndarray,
    sr: int,
    segments: list[tuple[float, float]],
    asr: ASR,
    roster: dict[str, str],
    cfg: TriggerCfg,
    speaker: Speaker | None = None,
) -> list[Trigger]:
    """ASR each speech segment (`audio.speech_segments`) and keep the ones that say a
    command. `t` is the segment's speech onset."""
    if not segments:
        return []
    clips = [samples[int(a * sr) : int(b * sr)] for a, b in segments]
    out: list[Trigger] = []
    for (t0, t1), text in zip(segments, asr(clips, sr), strict=True):
        found = parse_command(tokens(text), roster, cfg)
        if found is None:
            continue
        _, _, subject, score = found
        out.append(
            Trigger(
                id="", type="voice", t=t0, t_end=t1, transcript=text.strip(),
                subject_player_id=subject,
                by_player_id=speaker(samples, sr, t0, t1) if speaker else None,
                confidence=score,
            )
        )  # fmt: skip
    return out


def subject_from_transcript(transcript: str, roster: dict[str, str], cfg: TriggerCfg) -> str | None:
    """Re-read a stored transcript against today's roster (names are tagged after the run)."""
    found = parse_command(tokens(transcript or ""), roster, cfg)
    return found[2] if found else None


def whisper_asr(model_id: str, device: str | int | None = None) -> ASR:
    """Whisper through `transformers` (MIT weights; ROCm works through torch.cuda), one
    short clip per speech segment, batched."""
    import torch
    from transformers import pipeline

    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device != "cpu" else torch.float32
    asr = pipeline("automatic-speech-recognition", model=model_id, device=device, dtype=dtype)

    def run(clips: list[np.ndarray], sr: int) -> list[str]:
        res = asr(
            [{"raw": c.astype(np.float32), "sampling_rate": sr} for c in clips],
            batch_size=8,
            generate_kwargs={"language": "en", "task": "transcribe"},
        )
        return [r["text"] for r in res]

    return run


# --- resolution ------------------------------------------------------------------


def resolve(t: float, plays: list[Play], cfg: TriggerCfg) -> Play | None:
    """The play that most recently ended in [t - max_lag_s, t + early_s]."""
    cands = [p for p in plays if t - cfg.max_lag_s <= p.t_end <= t + cfg.early_s]
    return max(cands, key=lambda p: (p.t_end, p.t_start)) if cands else None


def make_clip(trigger: Trigger, play: Play, duration_s: float | None = None) -> Clip:
    owner = trigger.by_player_id or trigger.subject_player_id
    t1 = play.t_end + CLIP_PAD_S
    return Clip(
        id="c_" + trigger.id.removeprefix("tr_"),
        play_id=play.id,
        trigger_id=trigger.id,
        t_start=round(max(0.0, play.t_start - CLIP_PAD_S), 3),
        t_end=round(min(t1, duration_s) if duration_s else t1, 3),
        attribution=Attribution(
            owner_player_id=owner,
            by_player_id=trigger.by_player_id,
            subject_player_id=trigger.subject_player_id,
        ),
        participants=list(dict.fromkeys(p.player_id for p in play.participants)),
        source="user" if trigger.source == "user" else "auto",
    )


def apply(
    triggers: list[Trigger], plays: list[Play], cfg: TriggerCfg, duration_s: float | None = None
) -> list[Clip]:
    """Resolve every trigger (in time order), fill `play.trigger` with the latest one that
    landed on it, and return one clip per resolved trigger. Mutates both lists."""
    clips: list[Clip] = []
    for tr in sorted(triggers, key=lambda x: x.t):
        play = resolve(tr.t, plays, cfg)
        tr.play_id = play.id if play else None
        if play is None:
            tr.clip_id = None
            continue
        clip = make_clip(tr, play, duration_s)
        tr.clip_id = clip.id
        play.trigger = tr.model_copy(update={"play_id": None, "clip_id": None})
        clips.append(clip)
    return clips


def number(triggers: list[Trigger], prefix: str = "tr_") -> list[Trigger]:
    """Stable ids in time order for automatic triggers (`tr_0001`...)."""
    for n, tr in enumerate(sorted(triggers, key=lambda x: (x.t, x.type)), 1):
        tr.id = f"{prefix}{n:04d}"
    return sorted(triggers, key=lambda x: x.t)


def roster_names(players: list[dict[str, Any]]) -> dict[str, str]:
    """{name: player_id} for tagged players (game.json `players`)."""
    return {p["name"]: p["id"] for p in players if p.get("name")}
