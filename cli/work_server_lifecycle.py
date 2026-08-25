"""Real work server lifecycle — subprocess launcher with health polling."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

import requests


class RealWorkServerLifecycle:
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        cmd: list[str],
        process_starter: Callable[
            [list[str]], subprocess.Popen[bytes]
        ] = subprocess.Popen,
        health_getter: Callable[[str], requests.Response] = requests.get,
        clearance_poster: Callable[
            [str, dict[str, str]], requests.Response
        ] = lambda url, headers: requests.post(url, headers=headers),
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._cmd = cmd
        self._process_starter = process_starter
        self._health_getter = health_getter
        self._clearance_poster = clearance_poster
        self._clock = clock
        self._sleeper = sleeper
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def _health_url(self) -> str:
        return f"http://{self._host}:{self._port}/health"

    @property
    def _clearance_url(self) -> str:
        return f"http://{self._host}:{self._port}/api/clearance"

    def startup(self, timeout_s: int) -> None:
        self._process = self._process_starter(self._cmd)
        deadline = self._clock() + timeout_s
        while True:
            try:
                resp = self._health_getter(self._health_url)
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            if self._clock() >= deadline:
                raise TimeoutError("work_server did not become healthy")
            self._sleeper(0.5)

    def health_check(self) -> bool:
        try:
            resp = self._health_getter(self._health_url)
            if resp.status_code != 200:
                return False
            body = resp.json()
            return isinstance(body, dict) and body.get("status") == "ok"
        except Exception:
            return False

    def auth_failure_probe(self) -> int:
        headers = {
            "Authorization": "Bearer __smoke_probe__",
            "Content-Type": "application/json",
        }
        try:
            resp = self._clearance_poster(self._clearance_url, headers)
            return resp.status_code
        except Exception:
            return 0

    def shutdown(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        except Exception:
            pass
        self._process = None
