"""aiohttp HTTP work server.

Exposes four routes:
- GET  /health           — shallow liveness check, no auth required (REQ-9.1)
- POST /jobs             — batch URL submission (REQ-9.3)
- GET  /jobs/{id}        — job status polling (REQ-9.4)
- POST /api/clearance    — clearance payload ingestion, validation-only (CP1.3)

Auth is enforced by a @web.middleware bearer-token check using
hmac.compare_digest to avoid timing-side-channel attacks (REQ-9.2).

This module depends only on:
- aiohttp (stdlib-like HTTP framework)
- ports.work_queue (WorkQueuePort, not concrete adapters)
- core.exceptions.repository (DuplicateError)

No SQLAlchemy, no infrastructure.persistence, no infrastructure.jobs imports
are permitted here (import-linter enforced, REQ-9.8).
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

from aiohttp import web

from core.exceptions.repository import DuplicateError
from ports.work_queue import WorkQueuePort

logger = logging.getLogger(__name__)

# Typed application keys — avoids NotAppKeyWarning and prevents key collisions.
_KEY_PORT = web.AppKey("work_queue_port", WorkQueuePort)
_KEY_TOKEN = web.AppKey("work_server_token", str)
_KEY_EXEMPT = web.AppKey("auth_exempt_paths", set)
_KEY_CLEARANCE_STORE = web.AppKey("clearance_store", dict)

# ---------------------------------------------------------------------------
# /api/clearance — validation constants (CP1.3)
# ---------------------------------------------------------------------------

# Exact match only — no endswith/prefix tricks.
_CLEARANCE_ALLOWED_DOMAINS: frozenset[str] = frozenset({"fbref.com", ".fbref.com"})

# Characters that disqualify a domain value before allowlist lookup.
_DOMAIN_REJECT_CHARS: frozenset[str] = frozenset("/\\:@?#[]")

# Strict field allowlist for the clearance payload.
_CLEARANCE_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"domain", "profile_id", "worker_id", "observed_at", "expires_at", "clearance"}
)

# Maximum byte length for the clearance field value.
_CLEARANCE_MAX_BYTES: int = 64 * 1024  # 64 KB


def _parse_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 UTC-compatible string to a timezone-aware datetime.

    Accepts trailing Z (replaced with +00:00). Returns None for malformed input
    or naive datetimes.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


@web.middleware
async def bearer_auth_middleware(
    request: web.Request,
    handler: Any,
) -> web.Response:
    """Validate Authorization: Bearer <token> on all routes except /health.

    Uses hmac.compare_digest for constant-time comparison to prevent
    timing-side-channel token oracle attacks.

    Routes decorated with the _AUTH_EXEMPT key are passed through without
    authentication.
    """
    if request.match_info.route.resource is not None:
        # Check route-level auth exemption via app-level registry
        exempt_paths: set[str] = request.app.get(_KEY_EXEMPT, set())
        if request.path in exempt_paths:
            return cast(web.Response, await handler(request))

    token: str = request.app[_KEY_TOKEN]
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "unauthorized"}, status=401)

    provided = auth_header[len("Bearer ") :]
    if not hmac.compare_digest(provided, token):
        return web.json_response({"error": "unauthorized"}, status=401)

    return cast(web.Response, await handler(request))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _health(request: web.Request) -> web.Response:
    """GET /health — shallow liveness check, no DB connectivity required."""
    return web.json_response({"status": "ok"})


async def _post_jobs(request: web.Request) -> web.Response:
    """POST /jobs — batch URL submission.

    Accepts: {"urls": ["https://...", ...]}
    Returns 201: {"jobs": [...], "rejected": [...]}

    Each URL is enqueued independently. Duplicates and invalid URLs appear
    in rejected[] rather than causing the whole request to fail.
    """
    # Parse JSON body
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(body, dict) or "urls" not in body:
        return web.json_response({"error": "missing required field: urls"}, status=422)

    urls = body["urls"]
    if not isinstance(urls, list):
        return web.json_response({"error": "urls must be a list"}, status=422)

    port: WorkQueuePort = request.app[_KEY_PORT]
    jobs = []
    rejected = []

    for url in urls:
        # SSRF allowlist: only http/https fbref.com hostnames are permitted.
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme != "https":
            rejected.append({"url": url, "reason": "invalid scheme"})
            continue
        hostname = parsed.hostname or ""
        if not (hostname == "fbref.com" or hostname.endswith(".fbref.com")):
            rejected.append({"url": url, "reason": "host not allowed"})
            continue
        try:
            record = await port.enqueue(url)
            jobs.append(
                {
                    "id": record.id,
                    "url": record.url,
                    "status": record.status,
                }
            )
        except DuplicateError:
            rejected.append({"url": url, "reason": "duplicate"})
        except Exception as exc:
            logger.warning("Failed to enqueue URL %s: %s", url, exc)
            rejected.append({"url": url, "reason": "invalid"})

    return web.json_response({"jobs": jobs, "rejected": rejected}, status=201)


async def _get_job(request: web.Request) -> web.Response:
    """GET /jobs/{id} — return current job status.

    Returns 200 with job record, or 404 if not found.
    """
    try:
        job_id = int(request.match_info["id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid job id"}, status=400)

    port: WorkQueuePort = request.app[_KEY_PORT]
    record = await port.get_job(job_id)

    if record is None:
        return web.json_response({"error": "job not found"}, status=404)

    return web.json_response(
        {
            "id": record.id,
            "url": record.url,
            "status": record.status,
        }
    )


async def _post_clearance(request: web.Request) -> web.Response:
    """POST /api/clearance — validate clearance payload; no persistence (CP1.3).

    Accepts an authenticated JSON payload reporting browser/profile readiness.
    Returns 204 on success. Does not store, log, or echo sensitive values.
    """
    _invalid = web.json_response({"error": "invalid_request"}, status=422)

    # 1. Require application/json content type.
    if request.content_type != "application/json":
        return web.json_response({"error": "unsupported_media_type"}, status=415)

    # 2. Parse JSON body — invalid JSON → 400.
    try:
        body: Any = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid_request"}, status=400)

    # 3. Top-level must be a JSON object — non-object → 400.
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_request"}, status=400)

    # 4. Reject unknown fields (strict allowlist, case-sensitive key names).
    extra_keys = set(body.keys()) - _CLEARANCE_REQUIRED_KEYS
    if extra_keys:
        return _invalid

    # 5. Check required fields present.
    missing = _CLEARANCE_REQUIRED_KEYS - set(body.keys())
    if missing:
        return _invalid

    # 6. All required field values must be strings.
    for key in _CLEARANCE_REQUIRED_KEYS:
        if not isinstance(body[key], str):
            return _invalid

    # 7. Domain: reject-by-default allowlist.
    domain: str = body["domain"].strip().lower()
    if any(c in domain for c in _DOMAIN_REJECT_CHARS):
        return _invalid
    if domain not in _CLEARANCE_ALLOWED_DOMAINS:
        return _invalid

    # 8. Timestamps: parse and validate ordering + expiry.
    observed_at = _parse_utc(body["observed_at"])
    if observed_at is None:
        return _invalid
    expires_at = _parse_utc(body["expires_at"])
    if expires_at is None:
        return _invalid
    if expires_at <= observed_at:
        return _invalid
    if expires_at <= datetime.now(UTC):
        return _invalid

    # 9. Clearance field size limit.
    if len(body["clearance"].encode()) > _CLEARANCE_MAX_BYTES:
        return _invalid

    # 10. Accept — store sanitized metadata only (raw clearance never stored).
    store: dict[str, str] = request.app[_KEY_CLEARANCE_STORE]
    store.update(
        {
            "domain": domain,
            "expires_at": body["expires_at"],
            "observed_at": body["observed_at"],
        }
    )
    return web.Response(status=204)


async def _get_clearance_latest(request: web.Request) -> web.Response:
    """GET /api/clearance/latest — return sanitized clearance metadata.

    Returns 204 when no validated clearance has been received yet.
    Returns 200 + JSON with sanitized fields (domain, expires_at, observed_at)
    after at least one valid POST /api/clearance has been processed.
    Raw clearance cookie value is never included.
    """
    store: dict[str, str] = request.app[_KEY_CLEARANCE_STORE]
    if not store:
        return web.Response(status=204)
    return web.json_response(store)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(port_adapter: WorkQueuePort, token: str) -> web.Application:
    """Build and return a configured aiohttp Application.

    Args:
        port_adapter: WorkQueuePort implementation (real or test double).
        token: The bearer token value to validate against incoming requests.

    Returns:
        A configured aiohttp.web.Application ready to run via AppRunner.
    """
    app = web.Application(middlewares=[bearer_auth_middleware])

    # Store shared state on the app via typed keys
    app[_KEY_PORT] = port_adapter
    app[_KEY_TOKEN] = token
    app[_KEY_EXEMPT] = {"/health"}
    app[_KEY_CLEARANCE_STORE] = {}

    # Register routes
    app.router.add_get("/health", _health)
    app.router.add_post("/jobs", _post_jobs)
    app.router.add_get("/jobs/{id}", _get_job)
    app.router.add_post("/api/clearance", _post_clearance)
    app.router.add_get("/api/clearance/latest", _get_clearance_latest)

    return app
