"""Unit tests for core.application.retry_policy."""

from __future__ import annotations

from core.application.retry_policy import is_terminal


class TestIsTerminal:
    def test_below_ceiling(self) -> None:
        assert not is_terminal(0, 5)
        assert not is_terminal(2, 5)
        assert not is_terminal(3, 5)

    def test_at_ceiling(self) -> None:
        assert is_terminal(4, 5)

    def test_above_ceiling(self) -> None:
        assert is_terminal(5, 5)
        assert is_terminal(10, 5)

    def test_ceiling_of_one(self) -> None:
        """A ceiling of 1 means the first failure is terminal."""
        assert is_terminal(0, 1)

    def test_ceiling_of_zero_always_terminal(self) -> None:
        """A ceiling of 0 means every outcome is terminal."""
        assert is_terminal(0, 0)
