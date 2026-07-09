"""Tests for BaseService ABC.

BaseService is a thin stub in Phase 1. It will be extended in Phase 3 when
the first domain is implemented.
"""

import pytest

from ports.service import BaseService

# ---------------------------------------------------------------------------
# Concrete test subclass (defined here, not imported from production code)
# ---------------------------------------------------------------------------


class ConcreteService(BaseService):
    """Minimal concrete service for tests."""

    async def execute(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseService:
    def test_base_service_is_importable(self) -> None:
        """BaseService can be imported from core.base.service."""
        assert BaseService is not None

    def test_base_service_cannot_be_instantiated_directly(self) -> None:
        """BaseService is abstract — direct instantiation raises TypeError."""
        with pytest.raises(TypeError):
            BaseService()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """A concrete subclass implementing all abstract methods can be instantiated."""
        svc = ConcreteService()
        assert isinstance(svc, BaseService)
