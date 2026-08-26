"""RealClearancePostClient — posts a synthetic clearance probe to the work server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# Domain mapping for clearance class labels.
# Key format: "<cookie_name>@<domain>" (label only — never raw cookie value).
# To add a new scraping target, add an entry here:
#   "<cookie_name>@<new-domain>": ".<new-domain>"
# Example: "cf_clearance@transfermarkt.com": ".transfermarkt.com"
_CLEARANCE_CLASS_TO_DOMAIN: dict[str, str] = {
    "cf_clearance@fbref.com": ".fbref.com",
}

_SYNTHETIC_PROFILE_ID = "__smoke__"
_SYNTHETIC_WORKER_ID = "__smoke__"
_PLACEHOLDER_CLEARANCE = "__smoke_probe_clearance__"
_EXPIRES_OFFSET_S = 60


def _default_poster(url: str, headers: dict[str, str], body: bytes) -> tuple[int, int]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            response_body = resp.read()
            return resp.status, len(response_body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read()
        return exc.code, len(error_body)


class RealClearancePostClient:
    """Satisfies the ClearancePostClient protocol for real clearance harness gate 14.

    Posts a synthetic probe payload to POST /api/clearance on the work server.
    Raw cookie values are never used; all payload fields are fixed placeholders.
    All external interactions are injectable for deterministic testing.
    """

    def __init__(
        self,
        url: str,
        token: str,
        poster: Callable[
            [str, dict[str, str], bytes], tuple[int, int]
        ] = _default_poster,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = url
        self._token = token
        self._poster = poster
        self._clock = clock

    def __repr__(self) -> str:
        return f"RealClearancePostClient(url={self._url!r}, token=<redacted>)"

    def post(self, clearance_class: str) -> tuple[int, int]:
        """POST a synthetic clearance probe; return (status_code, body_bytes).

        Raises ValueError for unknown clearance_class labels.
        Raw cookie values are never sent — the clearance field is a fixed placeholder.
        """
        domain = _CLEARANCE_CLASS_TO_DOMAIN.get(clearance_class)
        if domain is None:
            raise ValueError(f"Unknown clearance_class label: {clearance_class!r}")

        now = self._clock()
        observed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (now + timedelta(seconds=_EXPIRES_OFFSET_S)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        payload = {
            "domain": domain,
            "profile_id": _SYNTHETIC_PROFILE_ID,
            "worker_id": _SYNTHETIC_WORKER_ID,
            "observed_at": observed_at,
            "expires_at": expires_at,
            "clearance": _PLACEHOLDER_CLEARANCE,
        }
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        return self._poster(self._url, headers, body)
