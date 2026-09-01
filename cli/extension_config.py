# cli/extension_config.py
"""ExtensionConfig — runtime config injected into chrome.storage.local for the
sportcrawl Chrome extension.

The extension reads its config from chrome.storage.local at startup and on every
cookie event. The harness must inject this config via CDP Runtime.evaluate AFTER
the browser is ready and BEFORE the clearance observation gate starts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class ExtensionConfig:
    """Immutable config payload for the sportcrawl Chrome extension.

    Fields:
        work_server_url:      Base URL of the work server (e.g. http://127.0.0.1:9731).
        work_server_token:    Bearer token for work server auth. Never logged.
        profile_id:           Stable profile identifier.
                              Must match /^[A-Za-z0-9_-]{1,64}$/.
        worker_id:            Stable worker identifier.
                              Must match /^[A-Za-z0-9_-]{1,64}$/.
        disable_task_polling: When True, the extension skips the task poll alarm.
                              Always True for smoke mode.
    """

    work_server_url: str
    work_server_token: str
    profile_id: str
    worker_id: str
    disable_task_polling: bool

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.profile_id):
            raise ValueError(
                f"profile_id {self.profile_id!r} must match /^[A-Za-z0-9_-]{{1,64}}$/"
            )
        if not _ID_RE.match(self.worker_id):
            raise ValueError(
                f"worker_id {self.worker_id!r} must match /^[A-Za-z0-9_-]{{1,64}}$/"
            )

    def __repr__(self) -> str:
        return (
            f"ExtensionConfig("
            f"work_server_url={self.work_server_url!r}, "
            f"work_server_token=<redacted>, "
            f"profile_id={self.profile_id!r}, "
            f"worker_id={self.worker_id!r}, "
            f"disable_task_polling={self.disable_task_polling!r}"
            f")"
        )

    def __str__(self) -> str:
        return self.__repr__()


def smoke_extension_config(url: str, token: str) -> ExtensionConfig:
    """Return an ExtensionConfig configured for smoke mode.

    profile_id and worker_id are fixed to "smoke".
    disable_task_polling is always True in smoke mode.
    """
    return ExtensionConfig(
        work_server_url=url,
        work_server_token=token,
        profile_id="smoke",
        worker_id="smoke",
        disable_task_polling=True,
    )
