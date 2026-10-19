"""Cloud mode (D-80, docs/aws-migration.md): REPLAY_STORAGE=s3 + REPLAY_JOBS=s3.

Every route keeps working on local Paths. `S3Storage` mirrors `games/{id}/...` from the
bucket into the scratch data dir (Lambda: /tmp) as call sites ask for paths, and writes
back what a request changed when it ends:

- `path(id, rel)` lists `games/{id}/{rel}` (one LIST per prefix per request, so JSON state
  is never served stale across Lambda instances) and downloads what changed since this
  instance last saw it (ETag). `game_dir(id)` does the same for the whole game.
- Media (video/audio, or anything over 64 MiB) becomes a sparse stub of the right size:
  `is_file()` checks hold and nothing in Lambda reads video bytes (/media redirects to S3).
- At the end of the request (`end`), files whose size/mtime changed are uploaded and
  files deleted locally are deleted from S3. `write_json` uploads at once.

Jobs live in S3 too (`S3Jobs`) and run on the hfbox remote runner, never in Lambda.
boto3 is imported here only: local mode never imports this module.
"""

from __future__ import annotations

import dataclasses
import json
import mimetypes
import posixpath
import secrets
import sqlite3
import time
from contextvars import ContextVar
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings
from .providers import NotConfiguredError
from .providers.index import LocalIndex
from .providers.profiles import LocalProfiles, _Tx
from .providers.storage import LocalStorage

STUB_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".wav", ".mp3", ".m4a", ".aac")
MAX_PULL_BYTES = 64 << 20
GET_TTL_S = 3600

# {"pulled": {game_id: {rel, ...}}, "touched": {game_id, ...}} for the current request
_scope: ContextVar[dict | None] = ContextVar("replay_s3_scope", default=None)


def s3_client():
    # s3v4 + the runtime's region: presigned URLs then name the regional endpoint
    return boto3.client("s3", config=Config(signature_version="s3v4"))


def safe_rel(rel: str) -> str | None:
    """`rel` normalised, or None when it is empty or leaves the game folder."""
    if not rel or "\\" in rel or "\x00" in rel:
        return None
    norm = posixpath.normpath(rel)
    if norm in (".", "..") or norm.startswith(("/", "../")):
        return None
    return norm


def load_secrets(s: Settings) -> Settings:
    """The three secrets from SSM (`REPLAY_SSM_PREFIX` + api-key / worker-key /
    upload-token-secret, SecureString), else env. Called once per cold start."""
    vals = {"api_key": s.api_key, "worker_key": s.worker_key,
            "upload_token_secret": s.upload_token_secret}  # fmt: skip
    if s.ssm_prefix:
        names = {f"{s.ssm_prefix}{n.replace('_', '-')}": n for n in vals}
        got = boto3.client("ssm").get_parameters(Names=list(names), WithDecryption=True)
        for p in got["Parameters"]:
            vals[names[p["Name"]]] = p["Value"]
    missing = [k for k, v in vals.items() if not v]
    if missing or not s.s3_bucket:
        raise ValueError(
            f"cloud mode needs REPLAY_S3_BUCKET and {', '.join(missing) or 'its secrets'} "
            "(SSM under REPLAY_SSM_PREFIX, or env)"
        )
    return dataclasses.replace(s, **vals)


# --------------------------------------------------------------------------- request scope


def begin():
    return _scope.set({"pulled": {}, "touched": set()})


def end(storage: S3Storage) -> None:
    """Write back every game this request touched (run before the scope is reset)."""
    scope = _scope.get()
    for game_id in sorted(scope["touched"]) if scope else ():
        storage.flush(game_id)


def reset(token) -> None:
    _scope.reset(token)


# --------------------------------------------------------------------------- storage


class S3Storage(LocalStorage):
    def __init__(self, bucket: str, games_dir: Path, client=None):
        super().__init__(games_dir)
        self.bucket = bucket
        self.s3 = client or s3_client()
        # game_id -> rel -> (etag, local size, local mtime_ns) as last pulled / pushed
        # ponytail: unlocked; Lambda serves one request at a time per instance
        self.seen: dict[str, dict[str, tuple[str, int, int]]] = {}

    def key(self, game_id: str, rel: str = "") -> str:
        return f"games/{game_id}/{rel}"

    # ---- the Storage protocol, mirrored

    def game_dir(self, game_id: str) -> Path:
        self._pull(game_id, "")
        return self.games_dir / game_id

    def path(self, game_id: str, rel: str) -> Path:
        self._pull(game_id, rel)
        return self.games_dir / game_id / rel

    def resolve_inside(self, game_id: str, rel: str) -> Path | None:
        clean = safe_rel(rel)
        return None if clean is None else self.path(game_id, clean)

    def write_json(self, game_id: str, rel: str, data: dict) -> None:
        super().write_json(game_id, rel, data)
        self._push(game_id, rel)

    def presign_get(self, game_id: str, rel: str, ttl_s: int = GET_TTL_S) -> str:
        params = {"Bucket": self.bucket, "Key": self.key(game_id, rel)}
        ctype = mimetypes.guess_type(rel)[0]
        if ctype:  # whatever the uploader sent, a <video> needs video/mp4
            params["ResponseContentType"] = ctype
        return self.s3.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_s)

    def presign_put(self, game_id: str, rel: str, ttl_s: int) -> str:
        params = {"Bucket": self.bucket, "Key": self.key(game_id, rel)}
        return self.s3.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_s)

    def listing(self, game_id: str, rel: str = "") -> dict[str, tuple[str, int]]:
        """{rel: (etag, size)} for every object at or under `rel`."""
        root = self.key(game_id)
        out = {}
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=root + rel
        )
        for page in pages:
            for o in page.get("Contents", []):
                r = o["Key"][len(root) :]
                if not rel or r == rel or r.startswith(rel.rstrip("/") + "/"):
                    out[r] = (o["ETag"], o["Size"])
        return out

    # ---- mirror

    def _pull(self, game_id: str, rel: str) -> None:
        if not game_id.replace("_", "").isalnum():
            return  # game ids are generated; never list someone's crafted prefix
        rel = rel.strip("/")
        scope = _scope.get()
        done = scope["pulled"].setdefault(game_id, set()) if scope else set()
        if "" in done or rel in done:
            return
        listing = self.listing(game_id, rel)
        seen = self.seen.setdefault(game_id, {})
        root = self.games_dir / game_id
        under = [r for r in seen if not rel or r == rel or r.startswith(rel + "/")]
        for r in under:  # deleted in S3 since we last looked
            if r not in listing:
                (root / r).unlink(missing_ok=True)
                del seen[r]
        for r, (etag, size) in listing.items():
            p = root / r
            if r in seen and seen[r][0] == etag and p.is_file():
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            if size > MAX_PULL_BYTES or r.lower().endswith(STUB_SUFFIXES):
                with p.open("wb") as fh:
                    fh.truncate(size)  # sparse: the right size, no bytes
            else:
                self.s3.download_file(self.bucket, self.key(game_id, r), str(p))
            st = p.stat()
            seen[r] = (etag, st.st_size, st.st_mtime_ns)
        root.mkdir(parents=True, exist_ok=True)
        if scope is not None:
            done.add(rel)
            scope["touched"].add(game_id)

    def _push(self, game_id: str, rel: str) -> None:
        p = self.games_dir / game_id / rel
        with p.open("rb") as fh:
            etag = self.s3.put_object(
                Bucket=self.bucket,
                Key=self.key(game_id, rel),
                Body=fh,
                ContentType=mimetypes.guess_type(rel)[0] or "application/octet-stream",
            )["ETag"]
        st = p.stat()
        self.seen.setdefault(game_id, {})[rel] = (etag, st.st_size, st.st_mtime_ns)

    def flush(self, game_id: str) -> None:
        """Upload what changed locally since the last pull/push; delete what was removed."""
        root = self.games_dir / game_id
        seen = self.seen.setdefault(game_id, {})
        for p in sorted(root.rglob("*")) if root.is_dir() else ():
            if not p.is_file() or p.name.endswith((".tmp", ".part")):
                continue
            r = p.relative_to(root).as_posix()
            st = p.stat()
            if seen.get(r, ("",))[1:] != (st.st_size, st.st_mtime_ns):
                self._push(game_id, r)
        for r in [r for r in seen if not (root / r).is_file()]:
            self.s3.delete_object(Bucket=self.bucket, Key=self.key(game_id, r))
            del seen[r]


class S3Index(LocalIndex):
    """`games/*/game.json` in the bucket; load/save go through the mirror."""

    storage: S3Storage

    def list(self) -> list[dict]:
        st = self.storage
        ids = []
        pages = st.s3.get_paginator("list_objects_v2").paginate(
            Bucket=st.bucket, Prefix="games/", Delimiter="/"
        )
        for page in pages:
            ids += [cp["Prefix"].split("/")[1] for cp in page.get("CommonPrefixes", [])]
        games = []
        # ponytail: one LIST (+ GET when changed) per game, serially; fine for tens of
        # games, a per-game summary object if the library grows to hundreds
        for game_id in ids:
            try:
                game = self.load(game_id)
            except (OSError, ValueError):
                continue
            if game is not None:
                games.append(game)
        games.sort(key=lambda g: g.get("recorded_at") or "", reverse=True)
        return games


# --------------------------------------------------------------------------- jobs


class S3Jobs:
    """`jobs/{job_id}.json` (LocalJobs' shape) + a queue marker `jobs/queue/{ts}-{job_id}`.
    Nothing runs here: the hfbox runner claims a job through /worker/claim, which takes
    `jobs/claims/{job_id}` with If-None-Match: *, so two runners never get the same job.
    Job ids carry the game id, so `for_game` lists one prefix.

    ponytail: no lease; a runner that dies mid-job leaves it `running` (visible, not
    lost). Re-queue by deleting the claim and writing a new queue marker.
    """

    KINDS = ("process", "autocalib")

    def __init__(self, storage: S3Storage):
        self.s3, self.bucket = storage.s3, storage.bucket

    def _key(self, job_id: str) -> str:
        return f"jobs/{job_id}.json"

    def _put(self, job: dict) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=self._key(job["id"]),
                           Body=json.dumps(job).encode(), ContentType="application/json")  # fmt: skip

    def submit(self, kind: str, game_id: str, fn=None, params: dict | None = None) -> dict:
        del fn  # the runner rebuilds the task from kind + params
        if kind not in self.KINDS:
            raise NotConfiguredError(f"{kind} jobs do not run in cloud mode yet")
        job_id = f"j_{game_id}_{secrets.token_hex(6)}"
        job = {
            "id": job_id,
            "kind": kind,
            "game_id": game_id,
            "status": "queued",
            "created_at": time.time(),
            "stage": None,
            "fraction": 0.0,
            "error": None,
            "params": params or {},
        }
        self._put(job)
        self.s3.put_object(Bucket=self.bucket, Key=f"jobs/queue/{time.time_ns():020d}-{job_id}",
                           Body=b"")  # fmt: skip
        return dict(job)

    def get(self, job_id: str) -> dict | None:
        if not job_id.replace("_", "").isalnum():
            return None
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self._key(job_id))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        return json.loads(obj["Body"].read())

    def update(self, job_id: str, **fields) -> dict:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job.update(fields)
        self._put(job)
        return job

    def progress(self, job_id: str, stage: str, fraction: float) -> None:
        self.update(job_id, stage=stage, fraction=round(float(fraction), 3))

    def for_game(self, game_id: str) -> list[dict]:
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=f"jobs/j_{game_id}_"
        )
        keys = [o["Key"] for page in pages for o in page.get("Contents", [])]
        jobs = [self.get(k[len("jobs/") : -len(".json")]) for k in keys]
        return [j for j in jobs if j]

    def claim(self) -> dict | None:
        """The oldest queued job, now `running` and ours, or None."""
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix="jobs/queue/"
        )
        for marker in sorted(o["Key"] for page in pages for o in page.get("Contents", [])):
            job_id = marker.rsplit("-", 1)[1]
            try:
                self.s3.put_object(Bucket=self.bucket, Key=f"jobs/claims/{job_id}", Body=b"",
                                   IfNoneMatch="*")  # fmt: skip
            except ClientError as exc:
                if exc.response["Error"]["Code"] in ("PreconditionFailed", "412",
                                                     "ConditionalRequestConflict"):  # fmt: skip
                    continue  # another runner has it
                raise
            self.s3.delete_object(Bucket=self.bucket, Key=marker)
            return self.update(job_id, status="running", started_at=time.time())
        return None


# --------------------------------------------------------------------------- profiles


class S3Profiles(LocalProfiles):
    """The SQLite file, mirrored to `profiles/profiles.sqlite`: re-downloaded when its
    ETag moved, uploaded after every transaction that changed a row. One writer assumed."""

    KEY = "profiles/profiles.sqlite"

    def __init__(self, path: Path, storage: S3Storage):
        self.s3, self.bucket, self.etag = storage.s3, storage.bucket, None
        super().__init__(path)

    def _refresh(self) -> None:
        try:
            etag = self.s3.head_object(Bucket=self.bucket, Key=self.KEY)["ETag"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return
            raise
        if etag != self.etag:
            self.s3.download_file(self.bucket, self.KEY, str(self.path))
            self.etag = etag

    def _push(self) -> None:
        with self.path.open("rb") as fh:
            self.etag = self.s3.put_object(Bucket=self.bucket, Key=self.KEY, Body=fh)["ETag"]

    def _db(self):
        self._refresh()
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return _PushTx(db, self._push)


class _PushTx(_Tx):
    def __init__(self, db: sqlite3.Connection, push):
        super().__init__(db)
        self.push = push

    def __exit__(self, *exc) -> None:
        changed = exc[0] is None and self.db.total_changes > 0
        super().__exit__(*exc)
        if changed:
            self.push()


# --------------------------------------------------------------------------- providers


class Unavailable:
    """A provider that needs an hfbox-local service (LLM_URL, model venvs, face models):
    every call raises NotConfiguredError, which cloud mode answers with 503."""

    def __init__(self, name: str):
        self.name = name

    def __getattr__(self, attr: str):
        def fail(*_a, **_k):
            raise NotConfiguredError(f"{self.name}: needs hfbox-local services, not in cloud mode")

        return fail
