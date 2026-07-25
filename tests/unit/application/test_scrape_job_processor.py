"""Unit tests for ScrapeJobProcessor.

Tests the success path, scraper failure, and non-retryable DB error.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from core.application.scrape_job_processor import ScrapeJobProcessor
from domains.player_info.models import PlayerInfoPage, PlayerInfoRawData
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(job_id: int = 1) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = "https://fbref.com/en/players/abc12345/Test-Player"
    row.status = ScrapeStatus.IN_PROGRESS
    row.job_type = "player_info"
    return row


def _make_raw_data() -> PlayerInfoRawData:
    return PlayerInfoRawData(
        player_id="abc12345",
        player_info_url="https://fbref.com/en/players/abc12345/Test-Player",
        fk_country_birth=None,
        country_birth_name="Argentina",
        national_team_name="Argentina",
        fk_national_team=None,
        city_name="Buenos Aires",
        player_born=None,
        player_height=180,
        player_weight=75,
        position_1="FW",
        position_2=None,
        position_3=None,
        player_foot="Right",
        player_wages=None,
        player_expires=None,
        photo_url=None,
    )


def _make_page(raw: PlayerInfoRawData) -> PlayerInfoPage:
    return PlayerInfoPage(players=[raw])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScrapeJobProcessorSuccess:
    async def test_success_path_calls_upsert_and_mark_done(self) -> None:
        """On success: parse is called, upsert_player_info called, mark_done called."""

        raw = _make_raw_data()
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()
        queue_repo.mark_failed = AsyncMock()

        country_name_cache: dict[str, str] = {"Argentina": "ARG"}
        position_cache: dict[str, int] = {}
        valid_countries: frozenset[str] = frozenset(["ARG"])

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache=country_name_cache,
            position_cache=position_cache,
            valid_countries=valid_countries,
        )

        html = "<html><body>player</body></html>"
        await processor.process(job, html)

        scraper.parse.assert_called_once_with(html)
        player_info_repo.upsert_player_info.assert_called_once()
        queue_repo.mark_done.assert_called_once_with(job.id)
        queue_repo.mark_failed.assert_not_called()

    async def test_success_resolves_country_from_cache(self) -> None:
        """country_birth_name → fk_country_birth resolved from country_name_cache."""

        raw = _make_raw_data()
        raw.country_birth_name = "Spain"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=2)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        country_name_cache = {"Spain": "ESP"}
        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache=country_name_cache,
            position_cache={},
            valid_countries=frozenset(["ESP"]),
        )

        await processor.process(job, "<html></html>")

        # The raw data passed to upsert should have fk_country_birth resolved
        call_args = player_info_repo.upsert_player_info.call_args
        upserted_raw: PlayerInfoRawData = call_args[0][0]
        assert upserted_raw.fk_country_birth == "ESP"


    async def test_success_resolves_youth_nat_team_from_cache(self) -> None:
        """youth_nat_team_name → fk_youth_nat_team resolved from country_name_cache."""

        raw = _make_raw_data()
        raw.youth_nat_team_name = "Spain"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=2)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        country_name_cache = {"Spain": "ESP"}
        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache=country_name_cache,
            position_cache={},
            valid_countries=frozenset(["ESP"]),
        )

        await processor.process(job, "<html></html>")

        call_args = player_info_repo.upsert_player_info.call_args
        upserted_raw: PlayerInfoRawData = call_args[0][0]
        assert upserted_raw.fk_youth_nat_team == "ESP"

    async def test_success_resolves_citizenship_and_calls_upsert_citizenship(
        self,
    ) -> None:
        """citizenship_name → fk_citizenship resolved; upsert_citizenship is called."""

        raw = _make_raw_data()
        raw.citizenship_name = "Argentina"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)
        player_info_repo.upsert_citizenship = AsyncMock()

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["ARG"]),
        )

        await processor.process(job, "<html></html>")

        player_info_repo.upsert_citizenship.assert_called_once_with("abc12345", "ARG")

    async def test_citizenship_not_called_when_name_is_none(self) -> None:
        """upsert_citizenship must NOT be called when citizenship_name is absent."""

        raw = _make_raw_data()
        raw.citizenship_name = None
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)
        player_info_repo.upsert_citizenship = AsyncMock()

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["ARG"]),
        )

        await processor.process(job, "<html></html>")

        player_info_repo.upsert_citizenship.assert_not_called()

    async def test_citizenship_not_called_when_country_not_in_valid_set(
        self,
    ) -> None:
        """upsert_citizenship must NOT be called when citizenship FK is invalid."""

        raw = _make_raw_data()
        raw.citizenship_name = "Argentina"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)
        player_info_repo.upsert_citizenship = AsyncMock()

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["BRA"]),  # ARG excluded
        )

        await processor.process(job, "<html></html>")

        player_info_repo.upsert_citizenship.assert_not_called()

    async def test_invalid_country_id_is_nullified(self) -> None:
        """FK country IDs not in valid_countries must be set to None before upsert."""

        raw = _make_raw_data()
        raw.country_birth_name = "Argentina"
        raw.national_team_name = "Argentina"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        # ARG is NOT in valid_countries — both FKs must be nullified
        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["BRA"]),
        )

        await processor.process(job, "<html></html>")

        call_args = player_info_repo.upsert_player_info.call_args
        upserted_raw: PlayerInfoRawData = call_args[0][0]
        assert upserted_raw.fk_country_birth is None
        assert upserted_raw.fk_national_team is None


class TestScrapeJobProcessorCityUpsert:
    async def test_upsert_city_called_when_city_name_is_set(self) -> None:
        """upsert_city must be called with city_name when it is not None."""
        raw = _make_raw_data()
        raw.city_name = "Buenos Aires"
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)
        player_info_repo.upsert_city = AsyncMock(return_value=55)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["ARG"]),
        )

        await processor.process(job, "<html></html>")

        player_info_repo.upsert_city.assert_called_once_with("Buenos Aires")
        # fk_city must be set on the raw object before upsert_player_info is called
        call_args = player_info_repo.upsert_player_info.call_args
        upserted_raw: PlayerInfoRawData = call_args[0][0]
        assert upserted_raw.fk_city == 55

    async def test_upsert_city_not_called_when_city_name_is_none(self) -> None:
        """upsert_city must NOT be called when city_name is None."""
        raw = _make_raw_data()
        raw.city_name = None
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock()
        player_info_repo.upsert_photo = AsyncMock()
        player_info_repo.upsert_position = AsyncMock(return_value=1)
        player_info_repo.upsert_city = AsyncMock(return_value=1)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={"Argentina": "ARG"},
            position_cache={},
            valid_countries=frozenset(["ARG"]),
        )

        await processor.process(job, "<html></html>")

        player_info_repo.upsert_city.assert_not_called()


class TestScrapeJobProcessorFailure:
    async def test_scraper_parse_error_calls_mark_failed(self) -> None:
        """If scraper.parse raises, processor calls mark_failed with the error."""

        job = _make_job()
        scraper = MagicMock()
        scraper.parse.side_effect = RuntimeError("parse exploded")

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()
        queue_repo.mark_failed = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=AsyncMock(),
            country_name_cache={},
            position_cache={},
            valid_countries=frozenset(),
        )

        await processor.process(job, "<html></html>")

        queue_repo.mark_failed.assert_called_once()
        queue_repo.mark_done.assert_not_called()

    async def test_db_upsert_error_calls_mark_failed(self) -> None:
        """If upsert_player_info raises, processor calls mark_failed."""

        raw = _make_raw_data()
        page = _make_page(raw)
        job = _make_job()

        scraper = MagicMock()
        scraper.parse.return_value = page

        player_info_repo = AsyncMock()
        player_info_repo.upsert_player_info = AsyncMock(
            side_effect=Exception("DB constraint violation")
        )
        player_info_repo.upsert_position = AsyncMock(return_value=1)

        queue_repo = AsyncMock()
        queue_repo.mark_done = AsyncMock()
        queue_repo.mark_failed = AsyncMock()

        processor = ScrapeJobProcessor(
            scraper=scraper,
            queue_repo=queue_repo,
            player_info_repo=player_info_repo,
            country_name_cache={},
            position_cache={},
            valid_countries=frozenset(),
        )

        await processor.process(job, "<html></html>")

        queue_repo.mark_failed.assert_called_once()
        queue_repo.mark_done.assert_not_called()
