"""URL validation against SSRF attack vectors.

Uses stdlib only (urllib.parse, ipaddress) plus core.exceptions.
No config/ports/infrastructure imports (import-linter: core is innermost layer).
"""

import ipaddress
from urllib.parse import urlparse

from core.exceptions.scraper import SSRFError


def validate_scrape_url(url: str, allowed_hosts: list[str]) -> str:
    """Validate a URL for SSRF safety and return the validated hostname.

    Checks (in order): https scheme, non-empty host, private/loopback IP
    literals, allowlist membership (with subdomain support).

    Args:
        url: The URL to validate.
        allowed_hosts: Hostnames allowed to be scraped (e.g. ["fbref.com"]).
            Subdomains are accepted (e.g. "widgets.fbref.com" matches "fbref.com").

    Returns:
        The validated hostname string.

    Raises:
        SSRFError: If the URL fails any SSRF check.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise SSRFError(url=url, reason="scheme must be https")

    host = parsed.hostname
    if not host:
        raise SSRFError(url=url, reason="missing host")

    # Block private IP literals absolutely — before allowlist check.
    # DNS rebinding protection (hostname → private IP via DNS) is Phase-5.
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise SSRFError(url=url, reason="private IP not allowed")
    except ValueError:
        pass  # hostname, not an IP literal

    if not any(
        host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts
    ):
        raise SSRFError(url=url, reason="host not in allowed_hosts")

    return host
