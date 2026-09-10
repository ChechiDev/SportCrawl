"""Sanitized URL validation for configured target URLs."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def validate_target_url(raw: str) -> str:
    """Validate and return the URL if safe; raise ValueError otherwise.

    Accepts only http/https URLs with a non-empty named hostname.
    Rejects: empty, whitespace-only, scheme-less, protocol-relative,
    non-http/https schemes, userinfo in netloc, missing hostname, and IP literals.
    Error messages are sanitized — raw URL values are never included.
    """
    url = raw.strip()
    if not url:
        raise ValueError("target URL must not be empty")

    parsed = urlparse(url)

    if not parsed.scheme:
        raise ValueError("target URL must include a scheme (http or https)")

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            "target URL scheme must be http or https, got an unsupported scheme"
        )

    if not parsed.hostname:
        raise ValueError("target URL must include a hostname")

    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass  # not an IP address — named host, continue
    else:
        raise ValueError("target URL must use a named host, not an IP address")

    if parsed.username or parsed.password:
        raise ValueError("target URL must not contain userinfo (credentials)")

    return url


def extract_hostname(raw: str) -> str:
    """Extract hostname from a validated URL. Call validate_target_url first."""
    return urlparse(raw).hostname or ""
