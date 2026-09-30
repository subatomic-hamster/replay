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
    smooth_window: int = 5
    # Seated officials and the bench: alive this long without leaving a circle this
    # wide (p90 radius) is not a player. See court.stationary.
    stationary_min_s: float = 20.0
    stationary_max_m: float = 0.5
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
