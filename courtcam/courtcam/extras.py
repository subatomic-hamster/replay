"""Optional dependencies. courtcam's core installs with permissive packages only; model
backends live behind pip extras (`courtcam[yolo]` is AGPL-3.0 ultralytics, see README)."""

from __future__ import annotations

import importlib.util


def require(extra: str, feature: str, *modules: str) -> None:
    """Raise ImportError naming the extra to install when any of `modules` is missing.
    Checked with `find_spec`, so a present package is not imported here."""
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing:
        raise ImportError(
            f"{feature} needs {', '.join(missing)} (not installed). "
            f"Install the extra: pip install 'courtcam[{extra}]'"
            + (" (ultralytics is AGPL-3.0)" if extra == "yolo" else "")
        )
