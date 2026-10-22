"""Alexa request verification (docs/alexa.md), as Amazon's "Host a custom skill as a web
service" requires of an HTTPS endpoint:

1. `SignatureCertChainUrl` is https://s3.amazonaws.com[:443]/echo.api/... (after
   normalising `..`), host and scheme case-insensitive, path case-sensitive.
2. The PEM chain there is valid now, its leaf names echo-api.amazon.com, and it chains
   to a trusted root (certifi's bundle). `cryptography`'s web-PKI verifier does all three.
3. `Signature-256` is the leaf key's RSA SHA-256 (PKCS#1 v1.5) signature of the raw body.
4. `request.timestamp` is within 150 s of now.

Any failure raises `Invalid`; the route answers 400. The skill id check is the route's.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import functools
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

MAX_SKEW_S = 150
SIGNER = "echo-api.amazon.com"
_PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.DOTALL)


class Invalid(Exception):
    """Not a genuine, fresh Alexa request."""


def check_cert_url(url: str | None) -> None:
    try:
        u = urlsplit(url or "")
        port = u.port
    except ValueError as exc:
        raise Invalid(f"bad cert URL: {exc}") from exc
    path = posixpath.normpath(u.path) if u.path else ""
    if (
        u.scheme.lower() != "https"
        or (u.hostname or "") != "s3.amazonaws.com"  # .hostname is lowercased
        or port not in (None, 443)
        or u.username is not None
        or not path.startswith("/echo.api/")
    ):
        raise Invalid(f"cert URL not allowed: {url!r}")


def _load_pems(data: bytes) -> list[x509.Certificate]:
    out = []
    for pem in _PEM.findall(data):
        try:  # one odd root in a bundle (negative serial) must not drop the rest
            out.append(x509.load_pem_x509_certificate(pem))
        except ValueError:
            continue
    return out


@functools.lru_cache(maxsize=1)
def trust_store() -> Store:
    return Store(_load_pems(Path(certifi.where()).read_bytes()))


@functools.lru_cache(maxsize=8)  # per URL, per Lambda instance; failures are not cached
def fetch_chain(url: str) -> tuple[x509.Certificate, ...]:
    r = httpx.get(url, timeout=3.0)
    r.raise_for_status()
    return tuple(_load_pems(r.content))


def check_chain(certs, now: datetime.datetime) -> None:
    """Leaf valid at `now`, SAN echo-api.amazon.com, chained to a trusted root."""
    if not certs:
        raise Invalid("empty cert chain")
    verifier = (
        PolicyBuilder().store(trust_store()).time(now).build_server_verifier(x509.DNSName(SIGNER))
    )
    try:
        verifier.verify(certs[0], list(certs[1:]))
    except VerificationError as exc:
        raise Invalid(f"cert chain: {exc}") from exc


def verify(cert_url: str | None, signature: str | None, body: bytes,
           now: datetime.datetime | None = None) -> dict:  # fmt: skip
    """The parsed request when it is a genuine Alexa request, else `Invalid`."""
    if not signature:
        raise Invalid("no Signature-256 header")
    check_cert_url(cert_url)
    now = now or datetime.datetime.now(datetime.UTC)
    try:
        certs = fetch_chain(cert_url)
    except httpx.HTTPError as exc:
        raise Invalid(f"cert chain fetch: {exc}") from exc
    check_chain(certs, now)
    key = certs[0].public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        raise Invalid("signing cert key is not RSA")
    try:
        sig = base64.b64decode(signature, validate=True)
        key.verify(sig, body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, binascii.Error, ValueError) as exc:
        raise Invalid("bad signature") from exc
    try:
        req = json.loads(body)
        ts = datetime.datetime.fromisoformat(req["request"]["timestamp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise Invalid("no request.timestamp") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.UTC)
    if abs((now - ts).total_seconds()) > MAX_SKEW_S:
        raise Invalid("timestamp too far from now")
    return req
