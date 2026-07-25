"""Unit tests for scrape_pipeline s1 (Teams) integration changes.

Verifies structural / import contracts and that CountryTeamsWorker is
instantiated without queue= in the pipeline.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations


class TestPipelineS1Imports:
    def test_pipeline_imports_seed_country_teams_queue(self) -> None:
        """Pipeline must import _seed_queue from scrape_country_teams."""
        import scripts.scrape_pipeline as pipeline

        # The alias _seed_country_teams_queue must exist in the pipeline module
        assert hasattr(pipeline, "_seed_country_teams_queue"), (
            "scrape_pipeline must expose _seed_country_teams_queue "
            "(imported as alias from scrape_country_teams._seed_queue)"
        )

    def test_pipeline_imports_team_list_queue_repository(self) -> None:
        """Pipeline must import TeamListQueueRepository for recover/count."""
        import scripts.scrape_pipeline as pipeline

        assert hasattr(pipeline, "TeamListQueueRepository"), (
            "scrape_pipeline must import TeamListQueueRepository"
        )

    def test_s1_queue_variable_absent_from_pipeline(self) -> None:
        """The old asyncio.Queue s1_queue variable must not exist in pipeline source."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        assert "s1_queue" not in src, (
            "s1_queue (asyncio.Queue) must be removed from scrape_pipeline.py"
        )

    def test_country_teams_worker_not_instantiated_with_queue(self) -> None:
        """CountryTeamsWorker in pipeline must not pass queue= keyword."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        # Check that queue=s1_queue is absent from the worker instantiation block
        assert "queue=s1_queue" not in src, (
            "scrape_pipeline must not pass queue=s1_queue to CountryTeamsWorker"
        )

    def test_pipeline_passes_url_to_country_to_worker(self) -> None:
        """CountryTeamsWorker in pipeline must receive url_to_country param."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        assert "url_to_country=" in src, (
            "scrape_pipeline must pass url_to_country= to CountryTeamsWorker"
        )

    def test_pipeline_passes_country_filter_to_worker(self) -> None:
        """CountryTeamsWorker in pipeline must receive country_filter param."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        assert "country_filter=" in src, (
            "scrape_pipeline must pass country_filter= to CountryTeamsWorker"
        )

    def test_pipeline_calls_recover_all_stale_for_team_list(self) -> None:
        """Pipeline must call recover_all_stale() for team_list jobs."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        assert "TeamListQueueRepository" in src and "recover_all_stale" in src, (
            "scrape_pipeline must call TeamListQueueRepository(...).recover_all_stale()"
        )

    def test_pipeline_s1_total_from_db_pending_count(self) -> None:
        """s1_total must be derived from DB PENDING count, not len(s1_rows)."""
        import pathlib

        src = pathlib.Path("scripts/scrape_pipeline.py").read_text()
        # After the change, len(s1_rows) must NOT be the source for s1_total
        assert "s1_total = len(s1_rows)" not in src, (
            "s1_total must be sourced from DB PENDING count, not len(s1_rows)"
        )
        assert "job_type='team_list' AND status='DONE'" in src, (
            "scrape_pipeline must query DB for team_list DONE count (for display offset)"
        )
        assert "tbl_country_squads" in src, (
            "scrape_pipeline must query total country_squads for s1_total denominator"
        )
