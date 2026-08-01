"""Process-owned Xvfb virtual framebuffer display.

XvfbDisplay is created once at the process/composition-root level and
shared across multiple PydollEngine instances. Engines that receive an
XvfbDisplay borrow it — they may call start() (idempotent) but MUST NOT
call stop(). Only the owner (the composition root) calls stop().

Engines that are not given a XvfbDisplay create and own one privately.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_XVFB_DISPLAY = ":199"
_READY_TIMEOUT_S = 5.0


class XvfbDisplay:
    """Owns exactly one Xvfb subprocess. start/stop are idempotent."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._display_env_set: bool = False

    @staticmethod
    def _display_alive(display: str) -> bool:
        """Return True if an X server is already listening on display."""
        try:
            result = subprocess.run(
                ["xdpyinfo", "-display", display],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            return False

    def start(self) -> None:
        """Start Xvfb if not already running. Idempotent.

        Safe to call when Xvfb or xdpyinfo are not installed (CI environments).
        Thread-safe: concurrent calls from asyncio.to_thread are serialized.
        """
        with self._lock:
            if self._proc is not None:
                return  # already managed by this instance

            if self._display_alive(_XVFB_DISPLAY):
                # An X server is already listening on :199 — reuse it without
                # setting _proc. Track that we set DISPLAY so stop() can
                # restore the environment when the owner shuts down.
                os.environ["DISPLAY"] = _XVFB_DISPLAY
                self._display_env_set = True
                return

            try:
                self._proc = subprocess.Popen(
                    ["Xvfb", _XVFB_DISPLAY, "-screen", "0", "1920x1080x24"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                logger.debug(
                    "Xvfb not found — Chrome will use existing DISPLAY or run headless"
                )
                return

            deadline = time.monotonic() + _READY_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._display_alive(_XVFB_DISPLAY):
                    os.environ["DISPLAY"] = _XVFB_DISPLAY
                    self._display_env_set = True
                    break
                time.sleep(0.1)
            else:
                logger.warning(
                    "Xvfb did not become ready within %.1fs — terminating",
                    _READY_TIMEOUT_S,
                )
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=3)
                self._proc = None

    def stop(self) -> None:
        """Terminate the owned Xvfb process and restore the environment.

        Idempotent. Thread-safe — serialized by the same lock as start().
        """
        with self._lock:
            if self._proc is not None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=3)
                self._proc = None
            if self._display_env_set:
                os.environ.pop("DISPLAY", None)
                self._display_env_set = False

    def __enter__(self) -> XvfbDisplay:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
