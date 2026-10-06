"""Content-hash cache: a stage's outputs, keyed by what produced them.

key = sha256(stage name + stage version + item + params + sha256 of every input).
An entry is a directory `<root>/<stage>/<key[:2]>/<key>/` holding the outputs in their
game-relative layout plus `meta.json`. It is built under a temp name and renamed into
place, so a crash mid-store leaves no half entry: a key either exists whole or not at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

# ponytail: media (>= 16 MiB) is hard-linked, everything else copied. courtcam writes its
# JSON in place (`path.write_text`), so a link would let a later in-place edit of a game
# file rewrite the cache entry; ffmpeg outputs are unlinked before a stage reruns.
# Reflinks (cp --reflink) would remove the threshold on a CoW filesystem.
LINK_MIN_BYTES = 16 << 20

_memo: dict[tuple[str, int, int], str] = {}
_memo_lock = threading.Lock()


def default_root() -> Path:
    env = os.environ.get("REPLAY_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    box = Path("/workspace/wt/replay-env")
    return box / "cache" if box.is_dir() else Path.home() / ".cache" / "replay-worker"


def file_hash(path: Path) -> str:
    """sha256 of a file, or of a directory's sorted (relpath, file hash) list.

    File hashes are memoised per (path, size, mtime) for the life of the process: the
    mezzanine is an input to most stages and can be gigabytes.
    """
    path = Path(path)
    if path.is_dir():
        h = hashlib.sha256()
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(f"{f.relative_to(path).as_posix()}\0{file_hash(f)}\0".encode())
        return h.hexdigest()
    st = path.stat()
    memo_key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    with _memo_lock:
        if memo_key in _memo:
            return _memo[memo_key]
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    with _memo_lock:
        _memo[memo_key] = h.hexdigest()
    return _memo[memo_key]


def task_key(stage: str, version: str, item: str | None, params: dict, inputs: dict) -> str:
    blob = json.dumps(
        {"stage": stage, "version": version, "item": item, "params": params, "inputs": inputs},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _place(src: Path, dst: Path) -> None:
    """Copy (or, for media, hard-link) a file or a tree from `src` to `dst`."""
    if src.is_dir():
        for f in src.rglob("*"):
            if f.is_file():
                _place(f, dst / f.relative_to(src))
        dst.mkdir(parents=True, exist_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.stat().st_size >= LINK_MIN_BYTES:
        try:
            os.link(src, dst)
            return
        except OSError:  # other filesystem: fall through to a copy
            pass
    shutil.copy2(src, dst)


class Cache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_root()

    def entry(self, stage: str, key: str) -> Path:
        return self.root / stage / key[:2] / key

    def has(self, stage: str, key: str) -> bool:
        return (self.entry(stage, key) / "meta.json").is_file()

    def store(self, stage: str, key: str, game_dir: Path, outputs: list[str], meta: dict) -> None:
        final = self.entry(stage, key)
        tmp = final.with_name(f"{key}.tmp-{os.getpid()}-{threading.get_ident()}")
        remove(tmp)
        for rel in outputs:
            src = Path(game_dir) / rel
            if not src.exists():
                remove(tmp)
                raise FileNotFoundError(f"stage {stage!r} did not write declared output {rel}")
            _place(src, tmp / rel)
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "meta.json").write_text(
            json.dumps({**meta, "outputs": outputs, "stored_at": time.time()}, indent=1)
        )
        try:
            tmp.rename(final)
        except OSError:  # a concurrent run stored the same key first; theirs is as good
            remove(tmp)

    def restore(self, stage: str, key: str, game_dir: Path, outputs: list[str]) -> None:
        entry = self.entry(stage, key)
        for rel in outputs:
            dst = Path(game_dir) / rel
            remove(dst)
            _place(entry / rel, dst)
