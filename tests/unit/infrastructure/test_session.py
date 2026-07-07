"""Unit tests for infrastructure/persistence/session.py.

Tests use mock sessions only — no real database required.
Satisfies R7 (session closed on context exit) and R13 (unit tests with mocks).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.persistence.session import get_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_factory() -> tuple[MagicMock, AsyncMock]:
    """Return (factory callable, mock session) for injection into get_session."""
    mock_session = AsyncMock()
    factory = MagicMock(return_value=mock_session)
    return factory, mock_session


# ---------------------------------------------------------------------------
# R7: Session closed on normal context exit
# ---------------------------------------------------------------------------


class TestSessionClosesOnNormalExit:
    async def test_close_is_awaited_after_block(self) -> None:
        """Session.close() must be awaited when the context manager exits normally."""
        factory, mock_session = _mock_factory()

        async with get_session(factory):
            pass

        mock_session.close.assert_awaited_once()

    async def test_yielded_object_is_session(self) -> None:
        """The yielded object must be the session returned by the factory."""
        factory, mock_session = _mock_factory()

        async with get_session(factory) as session:
            assert session is mock_session


# ---------------------------------------------------------------------------
# R7: Session closed on exception exit
# ---------------------------------------------------------------------------


class TestSessionClosesOnExceptionExit:
    async def test_close_called_when_exception_raised(self) -> None:
        """Session.close() must be awaited even if the context body raises."""
        factory, mock_session = _mock_factory()

        with pytest.raises(RuntimeError, match="boom"):
            async with get_session(factory):
                raise RuntimeError("boom")

        mock_session.close.assert_awaited_once()

    async def test_exception_propagates_after_close(self) -> None:
        """The original exception must propagate to the caller after close."""
        factory, mock_session = _mock_factory()

        with pytest.raises(ValueError, match="propagated"):
            async with get_session(factory):
                raise ValueError("propagated")

        mock_session.close.assert_awaited_once()
