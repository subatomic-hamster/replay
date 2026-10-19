"""D-80 routes (docs/aws-migration.md): the phone's multipart upload straight to S3 and
the hfbox remote runner's /worker API. Cloud mode only; the multipart routes answer 409
in local mode (the existing PUT /games/{id}/upload is the local path).

    POST /games/{id}/upload/multipart {size, content_type}  -> {upload_id, part_size, parts}
    POST /games/{id}/upload/complete  {upload_id, parts: [{n, etag}]}  -> the game
    POST /games/{id}/upload/abort     {upload_id}
    POST /worker/claim                           -> 204 | {job, game_id, files}
    POST /worker/jobs/{job_id}/progress {stage, fraction, ...}
    POST /worker/jobs/{job_id}/upload-urls {paths}  -> {path: presigned PUT}
    POST /worker/jobs/{job_id}/finish {ok, error?}
"""

from __future__ import annotations

import math
import time
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import pipeline_adapter as adapter

SOURCE_REL = "source.mp4"
CALIB_REL = "media/calib.jpg"
PART_BYTES = 16 << 20
MAX_PARTS = 1000
MAX_OBJECT_BYTES = 20 << 30
PUT_TTL_S = 6 * 3600
# job fields a runner may not overwrite through /progress
PROTECTED = {"id", "kind", "game_id", "status", "created_at", "params", "error"}


class MultipartInit(BaseModel):
    size: int = Field(gt=0, le=MAX_OBJECT_BYTES)
    content_type: str = Field(default="video/mp4", min_length=1, max_length=100)


class Part(BaseModel):
    n: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=200)


class MultipartComplete(BaseModel):
    upload_id: str = Field(min_length=1)
    parts: list[Part] = Field(min_length=1, max_length=10000)


class MultipartAbort(BaseModel):
    upload_id: str = Field(min_length=1)


class UploadUrls(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=5000)


class Finish(BaseModel):
    ok: bool
    error: str | None = Field(default=None, max_length=4000)


def register(app: FastAPI, game_or_404, resolve_urls) -> None:
    """The helpers come from main.py so there is one way to load and render a game."""

    def cloud_or_409(request: Request):
        st = request.app.state
        if not st.settings.cloud:
            raise HTTPException(409, "multipart upload is cloud mode only; PUT /upload instead")
        return st

    def s3_error(exc: Exception) -> HTTPException:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        return HTTPException(400, f"S3 refused the upload: {code}")

    @app.post("/games/{game_id}/upload/multipart")
    def multipart_init(request: Request, game_id: str, body: MultipartInit):
        st = cloud_or_409(request)
        game_or_404(request, game_id)
        part = PART_BYTES
        while math.ceil(body.size / part) > MAX_PARTS:
            part *= 2
        s3, bucket, key = st.storage.s3, st.storage.bucket, st.storage.key(game_id, SOURCE_REL)
        up = s3.create_multipart_upload(Bucket=bucket, Key=key, ContentType=body.content_type)
        params = {"Bucket": bucket, "Key": key, "UploadId": up["UploadId"]}
        urls = [
            {
                "n": n,
                "url": s3.generate_presigned_url(
                    "upload_part", Params={**params, "PartNumber": n}, ExpiresIn=PUT_TTL_S
                ),
            }
            for n in range(1, math.ceil(body.size / part) + 1)
        ]
        return {"upload_id": up["UploadId"], "part_size": part, "parts": urls}

    @app.post("/games/{game_id}/upload/complete")
    def multipart_complete(request: Request, game_id: str, body: MultipartComplete):
        st = cloud_or_409(request)
        game = game_or_404(request, game_id)
        storage = st.storage
        try:
            storage.s3.complete_multipart_upload(
                Bucket=storage.bucket,
                Key=storage.key(game_id, SOURCE_REL),
                UploadId=body.upload_id,
                MultipartUpload={"Parts": [{"PartNumber": p.n, "ETag": p.etag}
                                           for p in sorted(body.parts, key=lambda p: p.n)]},
            )  # fmt: skip
        except Exception as exc:  # botocore ClientError; boto3 is cloud-only
            raise s3_error(exc) from exc
        # Only an MP4/MOV ever reaches the decoder: anything else is dropped here.
        key = storage.key(game_id, SOURCE_REL)
        head = storage.s3.get_object(Bucket=storage.bucket, Key=key, Range="bytes=0-11")
        if not adapter.is_isobmff(head["Body"].read()):
            storage.s3.delete_object(Bucket=storage.bucket, Key=key)
            raise HTTPException(415, "the upload is not an MP4 or MOV video")
        # D-14: the frame to calibrate on, read through a presigned GET (no download)
        adapter.grab_frame_url(
            storage.presign_get(game_id, SOURCE_REL), storage.path(game_id, CALIB_REL), 5.0
        )
        game["status"] = "uploaded"
        st.index.save(game)
        return resolve_urls(game, storage, str(request.base_url).rstrip("/"))

    @app.post("/games/{game_id}/upload/abort")
    def multipart_abort(request: Request, game_id: str, body: MultipartAbort):
        st = cloud_or_409(request)
        game_or_404(request, game_id)
        try:
            st.storage.s3.abort_multipart_upload(Bucket=st.storage.bucket, UploadId=body.upload_id,
                                                 Key=st.storage.key(game_id, SOURCE_REL))  # fmt: skip
        except Exception as exc:
            raise s3_error(exc) from exc
        return {"ok": True}

    if not app.state.settings.cloud:
        return

    # ------------------------------------------------------------ remote runner (hfbox)

    def running(request: Request, job_id: str) -> dict:
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        if job["status"] != "running":
            raise HTTPException(409, f"job {job_id} is {job['status']}, not running")
        return job

    @app.post("/worker/claim")
    def worker_claim(request: Request):
        st = request.app.state
        job = st.jobs.claim()
        if job is None:
            return Response(status_code=204)
        gid = job["game_id"]
        files = [
            {"path": rel, "url": st.storage.presign_get(gid, rel), "size": size}
            for rel, (_etag, size) in sorted(st.storage.listing(gid).items())
        ]
        return {"job": job, "game_id": gid, "files": files}

    @app.post("/worker/jobs/{job_id}/progress")
    def worker_progress(request: Request, job_id: str, body: dict[str, Any] = Body(...)):  # noqa: B008
        running(request, job_id)
        fields = {k: v for k, v in body.items() if k not in PROTECTED}
        if "fraction" in fields:
            fields["fraction"] = round(float(fields["fraction"]), 3)
        return request.app.state.jobs.update(job_id, **fields)

    @app.post("/worker/jobs/{job_id}/upload-urls")
    def worker_upload_urls(request: Request, job_id: str, body: UploadUrls):
        from .cloud import safe_rel

        job = running(request, job_id)
        storage = request.app.state.storage
        out = {}
        for p in body.paths:
            rel = safe_rel(p)
            if rel is None:
                raise HTTPException(400, f"path {p!r} is not inside the game folder")
            out[p] = storage.presign_put(job["game_id"], rel, PUT_TTL_S)
        return out

    @app.post("/worker/jobs/{job_id}/finish")
    def worker_finish(request: Request, job_id: str, body: Finish):
        running(request, job_id)
        fields: dict[str, Any] = {"status": "done" if body.ok else "failed",
                                  "finished_at": time.time()}  # fmt: skip
        if not body.ok:
            fields["error"] = body.error or "the remote runner reported a failure"
        return request.app.state.jobs.update(job_id, **fields)
