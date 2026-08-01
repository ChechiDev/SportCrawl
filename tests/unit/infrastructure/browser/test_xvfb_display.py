"""Unit tests for XvfbDisplay — process-owned Xvfb virtual framebuffer manager."""
from __future__ import annotations

import os
from subprocess import Popen
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.browser.xvfb_display import XvfbDisplay


class TestXvfbDisplayStart:
    def test_start_launches_xvfb_when_not_running(self) -> None:
        """start() must spawn Xvfb when the display is not alive."""
        display = XvfbDisplay()
        mock_proc = MagicMock(spec=Popen)
        with (
            patch(
                "infrastructure.browser.xvfb_display.subprocess.Popen",
                return_value=mock_proc,
            ),
            # First call: display not alive (pre-start check);
            # second call: display alive (readiness poll after Popen).
            patch.object(
                XvfbDisplay, "_display_alive", side_effect=[False, True]
            ),
        ):
            display.start()
        assert display._proc is not None

    def test_start_reuses_existing_display(self) -> None:
        """start() must not spawn Xvfb if the display is already alive."""
        display = XvfbDisplay()
        with (
            patch.object(XvfbDisplay, "_display_alive", return_value=True),
            patch("infrastructure.browser.xvfb_display.subprocess.Popen") as mock_popen,
        ):
            display.start()
            mock_popen.assert_not_called()
            assert display._proc is None  # reused — not owned

    def test_start_is_idempotent(self) -> None:
        """Calling start() twice must not spawn two Xvfb processes."""
        display = XvfbDisplay()
        mock_proc = MagicMock(spec=Popen)
        display._proc = mock_proc  # simulate already started
        with patch(
            "infrastructure.browser.xvfb_display.subprocess.Popen",
        ) as mock_popen:
            display.start()
            # _proc is not None → early return; Popen must NOT be called
            mock_popen.assert_not_called()

    def test_start_handles_missing_xvfb(self) -> None:
        """start() must not raise if Xvfb binary is not installed."""
        display = XvfbDisplay()
        with (
            patch.object(XvfbDisplay, "_display_alive", return_value=False),
            patch(
                "infrastructure.browser.xvfb_display.subprocess.Popen",
                side_effect=FileNotFoundError,
            ),
        ):
            display.start()  # must not raise
            assert display._proc is None

    def test_start_terminates_xvfb_on_readiness_timeout(self) -> None:
        """start() must terminate the Xvfb process if it never becomes ready."""
        display = XvfbDisplay()
        mock_proc = MagicMock(spec=Popen)
        with (
            patch(
                "infrastructure.browser.xvfb_display.subprocess.Popen",
                return_value=mock_proc,
            ),
            # Display never becomes alive (neither pre-check nor readiness poll)
            patch.object(XvfbDisplay, "_display_alive", return_value=False),
            # Expire the deadline immediately so the while loop exits without running
            patch("infrastructure.browser.xvfb_display._READY_TIMEOUT_S", 0.0),
        ):
            display.start()
        mock_proc.terminate.assert_called_once()
        assert display._proc is None


class TestXvfbDisplayStop:
    def test_stop_terminates_owned_process(self) -> None:
        """stop() must terminate the Popen process when one was started."""
        display = XvfbDisplay()
        mock_proc = MagicMock(spec=Popen)
        display._proc = mock_proc
        display.stop()
        mock_proc.terminate.assert_called_once()
        assert display._proc is None

    def test_stop_is_idempotent(self) -> None:
        """stop() called twice must not raise."""
        display = XvfbDisplay()
        mock_proc = MagicMock(spec=Popen)
        display._proc = mock_proc
        display.stop()
        display.stop()  # second call — _proc is None now

    def test_stop_noop_when_never_started(self) -> None:
        """stop() must be a no-op when start() was never called."""
        display = XvfbDisplay()
        # _proc is None, _display_env_set is False — nothing to clean up
        display.stop()  # must not raise

    def test_stop_cleans_display_env_when_reusing_external_server(self) -> None:
        """stop() must pop DISPLAY when start() reused an existing X server."""
        display = XvfbDisplay()
        # Simulate start() having taken the external-X-server path
        os.environ["DISPLAY"] = ":199"
        display._display_env_set = True

        display.stop()

        assert not display._display_env_set
        assert "DISPLAY" not in os.environ


class TestXvfbDisplayContextManager:
    def test_context_manager_starts_and_stops(self) -> None:
        """__enter__/__exit__ must call start() and stop()."""
        with (
            patch.object(XvfbDisplay, "start") as mock_start,
            patch.object(XvfbDisplay, "stop") as mock_stop,
        ):
            with XvfbDisplay():
                mock_start.assert_called_once()
            mock_stop.assert_called_once()

    def test_context_manager_stops_on_exception(self) -> None:
        """stop() must be called even if the body raises."""
        with (
            patch.object(XvfbDisplay, "start"),
            patch.object(XvfbDisplay, "stop") as mock_stop,
        ):
            with pytest.raises(RuntimeError):
                with XvfbDisplay():
                    raise RuntimeError("test")
            mock_stop.assert_called_once()
