"""aiohttp HTTP work server.

Exposes three routes:
- GET  /health        — shallow liveness check, no auth required (REQ-9.1)
- POST /jobs          — batch URL submission (REQ-9.3)
- GET  /jobs/{id}     — job status polling (REQ-9.4)

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
from typing import Any

from aiohttp import web

from core.exceptions.repository import DuplicateError
from ports.work_queue import WorkQueuePort

logger = logging.getLogger(__name__)

# Typed application keys — avoids NotAppKeyWarning and prevents key collisions.
_KEY_PORT = web.AppKey("work_queue_port", WorkQueuePort)
_KEY_TOKEN = web.AppKey("work_server_token", str)
_KEY_EXEMPT = web.AppKey("auth_exempt_paths", set)


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
            return await handler(request)

    token: str = request.app[_KEY_TOKEN]
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "unauthorized"}, status=401)

    provided = auth_header[len("Bearer "):]
    if not hmac.compare_digest(provided, token):
        return web.json_response({"error": "unauthorized"}, status=401)

    return await handler(request)


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

    # Register routes
    app.router.add_get("/health", _health)
    app.router.add_post("/jobs", _post_jobs)
    app.router.add_get("/jobs/{id}", _get_job)

    return app
