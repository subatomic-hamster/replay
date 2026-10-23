""" "Replay, clip that" (plan §4.4 "Plays", vision "Replay, clip that").

Three trigger sources, one resolution rule:

* **gesture** — forearms crossed in an X, from the 2D keypoints of a tracked player
  (`poses/`) facing the camera: overhead (held >= `gesture_hold_s`), or in front of the
  chin or chest (held >= `gesture_front_hold_s`). The identity is the track's player id.
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

from .events import (
    L_EL,
    L_HIP,
    L_SH,
    L_WR,
    NOSE,
    R_EL,
    R_HIP,
    R_SH,
    R_WR,
    Signals,
    arms_up,
    elbow_spread,
    hands_overhead,
    x_pose,
)  # fmt: skip
from .extras import require
from .profiles import TriggerCfg
from .schema import Attribution, Clip, Play, Trigger

ASR = Callable[[list[np.ndarray], int], list[str]]  # (clips, sr) -> one text per clip
# (samples, sr, t0, t1) -> enrolled player id or None
Speaker = Callable[[np.ndarray, int, float, float], str | None]

CLIP_PAD_S = 1.0
THAT = {"that", "this", "it", "dat"}


# --- gesture ---------------------------------------------------------------------


def gesture_samples(kp: np.ndarray, cfg: TriggerCfg) -> tuple[np.ndarray, np.ndarray]:
    """(crossed, together): (n,) bools per pose sample. `crossed` is the strict X (wrists
    crossed overhead). `together` (only with `gesture_relaxed`) is the form a small
    player's pose gives: hands together overhead with the elbows apart (arms straight up
    to contest a shot keep the elbows by the head). A crossing whose arm keypoints all
    score >= `gesture_cross_kp` stands on its own: a turned player's elbows overlap in the
    image (0.3-0.5 torso on synthetic X holds) although the wrists are plainly crossed.
    A low-score crossing also needs the elbows apart: a pose model flips the side labels
    of an arms-up shot contest now and then (ViTPose on Kennesaw, arm scores 0.2-0.5)."""
    crossed = x_pose(kp, cfg.gesture_cross_kp) | (
        x_pose(kp, cfg.gesture_min_kp) & (elbow_spread(kp) >= cfg.gesture_elbow_min)
    )
    together = np.zeros_like(crossed)
    if cfg.gesture_relaxed:
        together = hands_overhead(
            kp, cfg.gesture_min_kp, cfg.gesture_up_min, cfg.gesture_gap_max, cfg.gesture_elbow_min
        )
    return crossed, together


L_EYE, R_EYE = 1, 2


def faces_camera(kp: np.ndarray, min_score: float) -> np.ndarray:
    """(n,) bool: the nose or an eye is scored, so the player faces the camera (front or
    side-on). The X is shown to the camera; from behind, hands clasped on the head are an
    overhead X in 2D (YOLO pose on the owner's game: nose and eyes 0.04-0.31 from behind,
    0.86-0.99 on every real X)."""
    if not len(kp):
        return np.zeros(0, bool)
    return kp[:, [NOSE, L_EYE, R_EYE], 2].max(axis=1) >= min_score


def front_samples(kp: np.ndarray, cfg: TriggerCfg) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(low, high, chest): (n,) bools per pose sample (`kp` (n, 17, 3) px), lengths in
    torsos.

    The X's shape at any height: touching wrists (<= `gesture_gap_max` apart) no more
    than `gesture_low_min` below the shoulders, each above its own elbow, elbows lifted
    (no more than `gesture_low_elbow` below the shoulders) and wider than the wrists by
    `gesture_conv_min` (the forearms converge). A pose model labels wrists by side, so the
    crossing itself shows up as two wrists touching. `low` is that shape below the
    overhead line (`gesture_up_min`: in front of the chin or chest), `high` above it.
    Hands together at the chin with the elbows down by the sides is a clap or a hand to
    the mouth, not an X (real footage: elbows 0.36-0.49 below the shoulders there,
    0.14-0.33 on real chest X's); a ball held at the chin keeps the wrists a ball apart.

    `chest`: wrists touching between chest height (the lower wrist no more than
    `gesture_chest_min` below the shoulders) and the overhead line, any elbows: arms
    crossed in front of the chest, maybe on their way up to an overhead X."""
    if not len(kp):
        z = np.zeros(0, bool)
        return z, z, z
    ok = (kp[:, [L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP], 2] >= cfg.gesture_min_kp).all(
        axis=1
    )
    sh_y = kp[:, [L_SH, R_SH], 1].mean(axis=1)
    torso = kp[:, [L_HIP, R_HIP], 1].mean(axis=1) - sh_y
    ok &= torso > 0
    torso = np.where(ok, torso, 1.0)
    up = (sh_y - kp[:, [L_WR, R_WR], 1].max(axis=1)) / torso  # the lower wrist
    # in 2D: the wrists of an X meet at the crossing, a throw's follow-through passes
    # them by at different heights
    gap = np.hypot(*(kp[:, L_WR, :2] - kp[:, R_WR, :2]).T) / torso
    touch = ok & (gap <= cfg.gesture_gap_max) & (up >= cfg.gesture_chest_min)
    elbow_up = (sh_y - kp[:, [L_EL, R_EL], 1].mean(axis=1)) / torso
    rise = np.minimum(kp[:, L_EL, 1] - kp[:, L_WR, 1], kp[:, R_EL, 1] - kp[:, R_WR, 1])
    shape = (
        touch
        & (up >= cfg.gesture_low_min)
        & (rise > 0)
        & (elbow_up >= cfg.gesture_low_elbow)
        & (elbow_spread(kp) - gap >= cfg.gesture_conv_min)
    )
    high = up >= cfg.gesture_up_min
    return shape & ~high, shape & high, touch & ~high


def held(ts: np.ndarray, hit: np.ndarray, hold: float, vote: float, max_gap: float):
    """[(first, last)] hit times of every hold: a window of `hold` s in which at least
    `vote` of the pose samples hit. Overlapping windows (or ones `max_gap` apart) merge.
    vote = 1 is the old strict run; < 1 rides out a few misread samples of a small player."""
    out: list[list[float]] = []
    hits = ts[hit]
    for t0 in hits:
        inside = (ts >= t0 - 1e-6) & (ts <= t0 + hold + 1e-6)
        if ts[inside][-1] < t0 + hold - 0.15:  # the window runs past the samples
            continue
        if hit[inside].mean() < vote - 1e-6:
            continue
        last = float(hits[(hits >= t0) & (hits <= t0 + hold + 1e-6)][-1])
        if out and t0 <= out[-1][1] + max_gap:
            out[-1][1] = max(out[-1][1], last)
        else:
            out.append([float(t0), last])
    return [(a, b) for a, b in out]


def _span(ts: np.ndarray, up: np.ndarray, a: float, b: float) -> float:
    """Length of the hold [a, b] widened over the `up` samples right around it."""
    i, j = int(np.searchsorted(ts, a)), int(np.searchsorted(ts, b))
    while i > 0 and up[i - 1]:
        i -= 1
    while j < len(ts) - 1 and up[j + 1]:
        j += 1
    return float(ts[j] - ts[i])


def detect_gestures(signals: Signals, cfg: TriggerCfg) -> list[Trigger]:
    """One trigger per held X: t_start = first X sample, t = last one. Only a player
    facing the camera (`faces_camera`) counts.

    A hold of uncrossed hands-together samples overhead counts only if the arms stay
    overhead for `gesture_together_min_s` around it: the shot detector calls arms up for
    up to `shot.release_max_s` a release, and a jump shot or a catch with the ball
    overhead is exactly hands together, elbows out (GT-pose synthetic shots hold it
    0.5-0.8 s, a real catch and set point 0.5 s; the X is held ~1 s). The front-on X
    (`front_samples`) adds two forms no ball pose takes, each held `gesture_front_hold_s`
    (real ones last 0.4-0.6 s): crossed in front of the chin or chest with the elbows
    lifted (`low`), and crossed at the chest (`chest`), then raised overhead (`high`) or
    the reverse, both parts held within one hold (a shot's gather holds the ball, wrists
    apart, and is over in a sample or two)."""
    out: list[Trigger] = []
    short = (cfg.gesture_front_hold_s, cfg.gesture_vote, cfg.gesture_max_gap_s)
    for pid in sorted(signals.poses):
        ts, kp = signals.kp_px(pid, -np.inf, np.inf)
        if not len(ts):
            continue
        face = faces_camera(kp, cfg.gesture_face_min)
        crossed, together = (s & face for s in gesture_samples(kp, cfg))
        low, high, chest = (s & face for s in front_samples(kp, cfg))
        args = (cfg.gesture_hold_s, cfg.gesture_vote, cfg.gesture_max_gap_s)
        # how long the arms stay overhead around the hold (an unscored sample is no
        # evidence they came down); the hands may drift apart now and then meanwhile
        up = arms_up(kp, cfg.gesture_min_kp, cfg.gesture_up_min)
        up |= ~(kp[:, [L_EL, R_EL, L_WR, R_WR], 2] >= cfg.gesture_min_kp).all(axis=1)
        holds = held(ts, crossed, *args) + [
            (a, b)
            for a, b in held(ts, crossed | together, *args)
            if _span(ts, up, a, b) >= cfg.gesture_together_min_s - 1e-6
        ]
        holds += held(ts, low, *short)
        over = crossed | together | high
        for a, b in held(ts, over | chest, *short):
            m = (ts >= a) & (ts <= b)
            if held(ts[m], over[m], *short) and held(ts[m], chest[m], *short):
                holds.append((a, b))
        merged: list[list[float]] = []
        for a, b in sorted(holds):
            if merged and a <= merged[-1][1] + cfg.gesture_max_gap_s:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            out.append(
                Trigger(
                    id="", type="gesture", t_start=round(a, 3), t=round(b, 3), by_player_id=pid,
                    confidence=round(min(0.95, 0.2 + 0.3 * (b - a) / cfg.gesture_hold_s), 3),
                )
            )  # fmt: skip
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
    require("asr", "Whisper ASR (asr_model)", "torch", "transformers")
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
