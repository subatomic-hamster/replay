"""Sport profiles: a YAML file plus a court template JSON, both in `courtcam/sports/`.

Everything sport-specific in the pipeline comes from here. Core modules must never
branch on the sport id (REPLAY_PLAN.md §12 rule 6).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

SPORTS_DIR = Path(__file__).parent / "sports"


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="allow")


class CourtTemplate(_Cfg):
    """Court geometry in metres, in the profile's origin convention (§4.5)."""

    name: str
    standard: str = "unknown"
    units: str = "m"
    origin: str = ""
    size: tuple[float, float]
    court: list[tuple[float, float]]
    rim: tuple[float, float] | None = None
    net_y: float | None = None
    rims: list[tuple[float, float]] = Field(default_factory=list)
    landmarks: dict[str, tuple[float, float]] = Field(default_factory=dict)
    features: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)

    @property
    def polygon(self) -> np.ndarray:
        """Court outline as an (N, 2) float array of metres."""
        return np.asarray(self.court, dtype=np.float64)

    def landmark_array(self, names: list[str]) -> np.ndarray:
        missing = [n for n in names if n not in self.landmarks]
        if missing:
            raise KeyError(f"template {self.name} has no landmark(s) {missing}")
        return np.asarray([self.landmarks[n] for n in names], dtype=np.float64)


class CourtCfg(_Cfg):
    template: str | None = None
    templates: dict[str, str] = Field(default_factory=dict)
    variants: list[str] = Field(default_factory=list)
    # Retired variant names that still load: an old game.json / landmarks.json keeps
    # its `variant`, and `template()` maps it onto the variant that replaced it.
    variant_aliases: dict[str, str] = Field(default_factory=dict)
    landmarks: list[str] = Field(default_factory=list)
    landmarks_optional: list[str] = Field(default_factory=list)
    margin_m: float = 1.0


class PlayersCfg(_Cfg):
    min: int = 2
    max: int = 10


class DetectionCfg(_Cfg):
    classes: list[str] = Field(default_factory=lambda: ["person"])
    stride: int = 2
    model: str = "yolo11n.pt"
    # Used instead of `model` when torch sees a GPU (ROCm too); None keeps `model`.
    # Measured in samples/real/RESULTS.md "Detection on the GPU".
    gpu_model: str | None = "yolo11m.pt"
    imgsz: int = 960
    conf: float = 0.25


class TrackingCfg(_Cfg):
    oncourt_min_fraction: float = 0.6
    min_lifetime_s: float = 1.0
    merge_max_gap_s: float = 1.5
    merge_max_dist_m: float = 2.0
    merge_overlap_s: float = 1.0  # a re-id'd person overlaps their old id by a few frames
    stitch_max_gap_s: float = 5.0  # identity._stitch: longest vanish a lane survives
    max_speed_mps: float = 8.0  # a sprinting player; bounds how far a stitch may reach
    # appearance re-ID in identity.merge_groups (0 = court distance only); a link whose
    # body-histogram distance (identity.app_distance) exceeds appearance_max is refused
    appearance_weight: float = 0.0
    appearance_max: float = 1.0
    # > 0: a merge link must also be within running reach, merge_reach_m + max_speed_mps
    # x gap (identity.merge_groups); 0 = merge_max_dist_m whatever the gap
    merge_reach_m: float = 0.0
    smooth_window: int = 5
    # Seated officials and the bench: alive this long without leaving a circle this
    # wide (p90 radius) is not a player. See court.stationary.
    stationary_min_s: float = 20.0
    stationary_max_m: float = 0.5
    # A merged player inside the painted lines (no margin) less than this share of the
    # time is the bench or the next court. Real players measured >= 0.53 (pickleball
    # near pair, who serve from behind the line); the bench / neighbours <= 0.31.
    inside_min_fraction: float = 0.4
    max_candidates: int = 400  # on-court tracklets handed to identity (merge is O(n^2))


class FollowCamCfg(_Cfg):
    zoom: float = 2.0
    lead_s: float = 0.3
    stiffness: float = 7.0


class TeamsCfg(_Cfg):
    """Fixed team colours. Net sports have no jersey signal (four people, four shirts),
    so `team_rule: net_side` paints the two sides from here instead of from the video."""

    colors: list[str] = Field(default_factory=list)


class ShotCfg(_Cfg):
    rim_radius_m: float = 7.0
    roi_px: int = 96
    min_gap_s: float = 2.0
    burst_sigma: float = 2.5
    pre_s: float = 3.0
    post_s: float = 2.0
    # Template features (closed with the baseline) inside which a shot is worth 2; any
    # other spot is a 3. Empty: shots get no `points`.
    two_pt_zones: list[str] = Field(default_factory=list)
    # The rim-ROI burst is the ball arriving; the shooter released it about this long
    # before, which is where their feet decide 2 vs 3.
    release_lead_s: float = 1.0
    # pose shots (events._pose_shots): arms up at most this long is a release, from
    # within this range of the rim, confirmed by a hoop-ROI burst this many robust sigmas
    # high in this window after the release
    release_max_s: float = 0.9
    # arms up = both wrists this many torso lengths above the shoulders (None: above the nose)
    release_up_min: float | None = None
    max_range_m: float = 9.0
    confirm_window_s: tuple[float, float] = (0.3, 2.2)
    confirm_sigma: float = 4.0
    # robust sigma floor (mean |frame diff| grey levels) for the hoop-ROI confirm
    confirm_mad_floor: float = 1e-6
    # put the hoop ROI where the full camera (calibrate.camera_calibration) projects the
    # rim, not straight up the image from the floor point under it
    hoop_from_camera: bool = False
    # Also watch the template's other rims (the far basket of a full court), projected
    # through the homography. Off: on the real Kennesaw ultra-wide the far rim projects
    # ~500 px from the real hoop, and every far-end "shot" came from that wrong ROI.
    # Synthetic full court: 7/7 shots with it, 3/7 without.
    extra_rims: bool = False
    # make/miss from what happens next (events.label_makes): an inbound by the other team
    # within `made_window_s` of the shot is a make, a rebound is a miss.
    made_window_s: float = 6.0


class PossessionCfg(_Cfg):
    """Basketball possession from team geometry (`events.detect_possessions`): the team
    whose players are on average farther from the attacked rim has the ball (defenders
    stand between their man and the basket)."""

    rate_hz: float = 5.0
    smooth_s: float = 2.0  # majority vote window over the per-tick offense label
    min_hold_s: float = 2.5  # a flip must hold this long to count
    min_gap_m: float = 0.6  # mean-distance difference below this is "unclear"
    rebound_window_s: float = 4.0  # flip within this of a shot: defensive rebound
    inbound_depth_m: float = 0.3  # a player this far behind the end line: inbound


class PoseCfg(_Cfg):
    """2D pose per tracked player on a crop around its track box (`courtcam.pose`)."""

    model: str = "yolo11m-pose.pt"
    # crops are letterboxed up to this: a 60 px far player gets ~5x. 640 cost 6x the time
    # on synthetic basketball (185 s vs 30 s for 90 s of video) and found fewer shots.
    imgsz: int = 384
    margin: float = 0.25  # crop margin per side, as a fraction of the box
    conf: float = 0.25
    min_iou: float = 0.3  # the crop's detection must overlap the track box this much
    # `--pose vit` (pose.vitpose_poser): top-down ViTPose on the track box itself; a local
    # directory or an HF repo id (Apache-2.0 weights)
    vit_model: str = "usyd-community/vitpose-base-simple"
    vit_top: float = 0.0  # grow the box upward by this fraction of its height (raised arms)


class AudioCfg(_Cfg):
    """Onsets (spectral flux) and loudness spikes (`courtcam.audio`)."""

    onset_k: float = 4.0  # peak > local median + k * MAD
    onset_min_gap_s: float = 0.12
    onset_min_strength: float = 0.0
    hype_db: float = 8.0  # loudness this far above the rolling median baseline
    hype_min_s: float = 0.6
    # A crowd is aperiodic, one voice or a whistle is not. Synthetic: crowd 0.21-0.25,
    # TTS "Replay, clip that" 0.47-0.61 (median over the run, 32 ms frames).
    hype_max_voiced: float = 0.38
    # speech gate for the voice-trigger ASR (audio.speech_segments)
    speech_db: float = 6.0
    speech_min_voiced: float = 0.36
    speech_gap_s: float = 0.4
    speech_min_s: float = 0.4
    speech_max_s: float = 8.0


class TriggerCfg(_Cfg):
    """ "Replay, clip that" (`courtcam.triggers`)."""

    gesture_hold_s: float = 0.8
    gesture_max_gap_s: float = 0.3  # one missed pose sample does not break a hold
    gesture_min_kp: float = 0.2  # keypoint score floor (a 60 px player's arms score 0.2-0.4)
    # share of the pose samples in a gesture_hold_s window that must show the X (1 = all);
    # small players drop keypoints, so a strict all-samples hold almost never survives
    gesture_vote: float = 0.6
    # also accept hands together overhead (events.hands_overhead): wrists >= up_min torso
    # above the shoulders, <= gap_max torso apart across, elbows >= elbow_min torso apart
    # (the elbow spread keeps arms-straight-up contests out: 0 false on 480 s of real)
    gesture_relaxed: bool = True
    gesture_up_min: float = 0.2
    gesture_gap_max: float = 0.3
    gesture_elbow_min: float = 0.5
    # a crossing with every arm keypoint at or above this score needs no elbow spread
    # (GT poses score 0.9 visible / 0.4 occluded; flipped side labels score lower)
    gesture_cross_kp: float = 0.35
    # around an uncrossed hands-together hold the arms must stay overhead this long
    # (= shot.release_max_s): shorter is a shot release with the ball overhead, not an X
    gesture_together_min_s: float = 0.9
    wake: str = "replay"
    command: str = "clip"
    fuzzy: float = 0.7  # difflib ratio for wake word / command / roster names
    max_lag_s: float = 8.0  # trigger at T resolves to a play ending in [T - max_lag, T + early]
    early_s: float = 0.5


class RallyCfg(_Cfg):
    """Net-sport rally segmentation from player motion (`events.detect_rallies`).

    Defaults measured on hand-labelled real clips (samples/real/RESULTS.md, "Rally
    segmentation"); a profile overrides them in its `rally:` block."""

    min_duration_s: float = 2.0
    max_gap_s: float = 1.5
    expected_contact_hz: list[float] = Field(default_factory=lambda: [0.8, 3.0])
    rate_hz: float = 10.0
    smooth_s: float = 2.5
    # Median court speed of the players on court, m/s. A run above `off_mps` that peaks
    # above `on_mps` is a rally; before a serve everyone stands still (< 0.3 m/s).
    on_mps: float = 0.9
    off_mps: float = 0.5
    max_speed_mps: float = 6.0  # faster than a person: a tracker or homography jump
    lead_s: float = 1.0  # the serve happens before the burst of movement it starts
    tail_s: float = 0.5  # after the last burst: the shuttle is still in the air
    # Audio fusion (events.fuse_rallies): contact onsets within `onset_pad_s` of a motion
    # rally snap its start to the first contact (the serve) and its end to the last one,
    # and split it at long silences. Off by default: on real badminton (auditorium 240 s,
    # 14 hand-labelled rallies) motion alone scored P 1.00 / R 0.86, fusion P 0.36 / R 0.36
    # (real hits are weaker onsets than the synthetic ones). Off, onsets inside a motion
    # rally above `contact_min_strength` are still its contacts.
    audio_fusion: bool = False
    onset_pad_s: float = 1.5
    contact_window_s: float = 0.3  # pose wrist motion this close to an onset names the hitter
    # onset strength (robust sigmas over the local median) a contact needs. Synthetic:
    # racket/hand contacts 50-90, bounces/footsteps/cheer onsets mostly < 30.
    contact_min_strength: float = 30.0
    # A run of at least this many contacts outside every motion rally is a rally on its
    # own (0: never). Off by default: measured only on synthetic volleyball.
    audio_only_min_contacts: int = 0
    # Point winner = the side serving next (events.assign_winners). The serving side is
    # the side of the player standing deepest behind their baseline when this is on
    # (volleyball: the server is alone behind the end line), else the first contact's team.
    server_behind_line: bool = False
    server_min_depth_m: float = 0.3


class Profile(_Cfg):
    id: str
    display_name: str
    tier: int = 1
    court: CourtCfg
    players: PlayersCfg = Field(default_factory=PlayersCfg)
    team_rule: str = "jersey_color"
    teams: TeamsCfg = Field(default_factory=TeamsCfg)
    detection: DetectionCfg = Field(default_factory=DetectionCfg)
    tracking: TrackingCfg = Field(default_factory=TrackingCfg)
    events: list[str] = Field(default_factory=list)
    shot: ShotCfg = Field(default_factory=ShotCfg)
    rally: RallyCfg = Field(default_factory=RallyCfg)
    possession: PossessionCfg = Field(default_factory=PossessionCfg)
    pose: PoseCfg = Field(default_factory=PoseCfg)
    audio: AudioCfg = Field(default_factory=AudioCfg)
    triggers: TriggerCfg = Field(default_factory=TriggerCfg)
    # Play grammars (courtcam.plays), each a dict; see plays.Grammar. Empty: no plays.
    plays: list[dict[str, Any]] = Field(default_factory=list)
    followcam: FollowCamCfg = Field(default_factory=FollowCamCfg)
    query_vocab: dict[str, Any] = Field(default_factory=dict)
    sport_ui: dict[str, Any] = Field(default_factory=dict)

    _dir: Path = Path(".")

    def default_variant(self) -> str:
        return self.court.variants[0] if self.court.variants else "default"

    def template(self, variant: str | None = None) -> CourtTemplate:
        variant = variant or self.default_variant()
        variant = self.court.variant_aliases.get(variant, variant)
        if self.court.variants and variant not in self.court.variants:
            raise ValueError(f"{self.id}: unknown variant {variant!r}; have {self.court.variants}")
        name = self.court.templates.get(variant) or self.court.template
        if not name:
            raise ValueError(f"{self.id}: no court template for variant {variant!r}")
        return load_template(self._dir / name)


@lru_cache(maxsize=16)
def load_template(path: Path) -> CourtTemplate:
    return CourtTemplate.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=16)
def load_profile(sport: str, sports_dir: Path = SPORTS_DIR) -> Profile:
    """Load `<sports_dir>/<sport>.yaml`. `sport` may also be a path to a YAML file."""
    path = Path(sport)
    if not path.is_file():
        path = sports_dir / f"{sport}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no sport profile at {path}")
    profile = Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    profile._dir = path.parent
    return profile


def available_sports(sports_dir: Path = SPORTS_DIR) -> list[str]:
    return sorted(p.stem for p in sports_dir.glob("*.yaml"))
