"""Tests for BaseRepository[T] generic CRUD class.

Uses mock AsyncSession only — no database required.
ConcreteTestRepository is defined here for test purposes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.exceptions.repository import DuplicateError, RepositoryError
from ports.repository import BaseRepository

# ---------------------------------------------------------------------------
# Minimal in-file ORM model (no real DB needed — session is fully mocked)
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class FakeModel(_TestBase):
    __tablename__ = "fake_model_for_tests"
    id: Mapped[int] = mapped_column(primary_key=True)


# ---------------------------------------------------------------------------
# Concrete test subclass
# ---------------------------------------------------------------------------


class ConcreteTestRepository(BaseRepository[FakeModel]):
    _model_class = FakeModel


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_concrete_subclass_can_be_instantiated(self) -> None:
        session = AsyncMock()
        repo = ConcreteTestRepository(session)
        assert repo._session is session

    def test_subclass_without_model_class_raises_type_error(self) -> None:
        """__init_subclass__ guard fires at class definition time."""
        with pytest.raises(TypeError, match="_model_class"):

            class _BadRepository(BaseRepository[FakeModel]):  # type: ignore[type-arg]  # pyright: ignore[reportUnusedClass]
                pass  # deliberately no _model_class


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_get_delegates_to_session_and_returns_entity(self) -> None:
        session = AsyncMock()
        entity = FakeModel()
        session.get.return_value = entity

        repo = ConcreteTestRepository(session)
        result = await repo.get(1)

        session.get.assert_called_once_with(FakeModel, 1)
        assert result is entity

    async def test_get_returns_none_when_entity_absent(self) -> None:
        session = AsyncMock()
        session.get.return_value = None

        repo = ConcreteTestRepository(session)
        result = await repo.get(999)

        assert result is None

    async def test_get_wraps_sqlalchemy_error_as_repository_error(self) -> None:
        session = AsyncMock()
        session.get.side_effect = SQLAlchemyError("connection lost")

        repo = ConcreteTestRepository(session)
        with pytest.raises(RepositoryError):
            await repo.get(1)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_adds_flushes_refreshes_and_returns_entity(self) -> None:
        session = AsyncMock()
        entity = FakeModel()

        repo = ConcreteTestRepository(session)
        result = await repo.create(entity)

        session.add.assert_called_once_with(entity)
        session.flush.assert_called_once()
        session.refresh.assert_called_once_with(entity)
        assert result is entity

    async def test_create_never_commits(self) -> None:
        """Caller owns the transaction; create must NOT call commit."""
        session = AsyncMock()
        entity = FakeModel()

        repo = ConcreteTestRepository(session)
        await repo.create(entity)

        session.commit.assert_not_called()

    async def test_create_raises_duplicate_error_on_integrity_error(self) -> None:
        session = AsyncMock()
        entity = FakeModel()
        session.flush.side_effect = IntegrityError(
            "statement", {}, Exception("unique constraint")
        )

        repo = ConcreteTestRepository(session)
        with pytest.raises(DuplicateError):
            await repo.create(entity)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_merges_flushes_and_returns_merged_entity(self) -> None:
        session = AsyncMock()
        entity = FakeModel()
        merged = FakeModel()
        session.merge.return_value = merged

        repo = ConcreteTestRepository(session)
        result = await repo.update(entity)

        session.merge.assert_called_once_with(entity)
        session.flush.assert_called_once()
        assert result is merged

    async def test_update_wraps_sqlalchemy_error_as_repository_error(self) -> None:
        session = AsyncMock()
        session.merge.side_effect = SQLAlchemyError("merge failed")

        repo = ConcreteTestRepository(session)
        with pytest.raises(RepositoryError):
            await repo.update(FakeModel())


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_removes_entity_and_returns_true(self) -> None:
        session = AsyncMock()
        entity = FakeModel()
        session.get.return_value = entity

        repo = ConcreteTestRepository(session)
        result = await repo.delete(1)

        session.delete.assert_called_once_with(entity)
        session.flush.assert_called_once()
        assert result is True

    async def test_delete_returns_false_when_entity_not_found(self) -> None:
        session = AsyncMock()
        session.get.return_value = None

        repo = ConcreteTestRepository(session)
        result = await repo.delete(999)

        session.delete.assert_not_called()
        assert result is False

    async def test_delete_wraps_sqlalchemy_error_as_repository_error(self) -> None:
        session = AsyncMock()
        session.get.side_effect = SQLAlchemyError("get failed")

        repo = ConcreteTestRepository(session)
        with pytest.raises(RepositoryError):
            await repo.delete(1)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    async def test_list_executes_select_and_returns_results(self) -> None:
        session = AsyncMock()
        entity1, entity2 = FakeModel(), FakeModel()
        # execute is async but its return value (the result set) is synchronous.
        # Use MagicMock so that result.scalars().all() returns a plain list.
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [entity1, entity2]
        session.execute.return_value = result_mock

        repo = ConcreteTestRepository(session)
        result = await repo.list()

        session.execute.assert_called_once()
        assert result == [entity1, entity2]

    async def test_list_wraps_sqlalchemy_error_as_repository_error(self) -> None:
        session = AsyncMock()
        session.execute.side_effect = SQLAlchemyError("query failed")

        repo = ConcreteTestRepository(session)
        with pytest.raises(RepositoryError):
            await repo.list()


# ---------------------------------------------------------------------------
# list — pagination
# ---------------------------------------------------------------------------


class TestListPagination:
    """REQ-6.2: list() must accept limit and offset for pagination."""

    def _make_repo_and_session(self) -> tuple[ConcreteTestRepository, AsyncMock]:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute.return_value = result_mock
        repo = ConcreteTestRepository(session)
        return repo, session

    async def test_list_with_limit_applies_limit_clause(self) -> None:
        """list(limit=3) must generate a statement with .limit(3)."""
        repo, session = self._make_repo_and_session()

        await repo.list(limit=3)

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        # The compiled statement must include LIMIT
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 3" in compiled.upper(), (
            f"Expected LIMIT clause in compiled SQL, got: {compiled!r}"
        )

    async def test_list_with_offset_applies_offset_clause(self) -> None:
        """list(offset=5) must generate a statement with .offset(5)."""
        repo, session = self._make_repo_and_session()

        await repo.list(offset=5)

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "OFFSET 5" in compiled.upper() or "offset" in compiled.lower(), (
            f"Expected OFFSET clause in compiled SQL, got: {compiled!r}"
        )

    async def test_list_with_limit_and_offset_applies_both(self) -> None:
        """list(limit=3, offset=5) must generate a statement with both clauses."""
        repo, session = self._make_repo_and_session()

        await repo.list(limit=3, offset=5)

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        compiled_upper = compiled.upper()
        assert "LIMIT 3" in compiled_upper or "limit" in compiled.lower(), (
            f"Expected LIMIT in compiled SQL, got: {compiled!r}"
        )
        assert "OFFSET 5" in compiled_upper, (
            f"Expected OFFSET in compiled SQL, got: {compiled!r}"
        )

    async def test_list_no_args_is_backwards_compatible(self) -> None:
        """list() with no pagination args must not break existing behaviour."""
        session = AsyncMock()
        entity1, entity2 = FakeModel(), FakeModel()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [entity1, entity2]
        session.execute.return_value = result_mock

        repo = ConcreteTestRepository(session)
        result = await repo.list()

        # Still returns all rows and calls execute exactly once.
        session.execute.assert_called_once()
        assert result == [entity1, entity2]

    async def test_list_limit_zero_returns_empty_list(self) -> None:
        """list(limit=0) must return an empty list without hitting the database."""
        repo, session = self._make_repo_and_session()

        result = await repo.list(limit=0)

        assert result == []
        session.execute.assert_not_called()

    async def test_list_negative_limit_raises_value_error(self) -> None:
        """list(limit=-1) must raise ValueError before touching the database."""
        repo, session = self._make_repo_and_session()

        with pytest.raises(ValueError, match="limit must be >= 0"):
            await repo.list(limit=-1)

        session.execute.assert_not_called()

    async def test_list_negative_offset_raises_value_error(self) -> None:
        """list(offset=-1) must raise ValueError before touching the database."""
        repo, session = self._make_repo_and_session()

        with pytest.raises(ValueError, match="offset must be >= 0"):
            await repo.list(offset=-1)

        session.execute.assert_not_called()
