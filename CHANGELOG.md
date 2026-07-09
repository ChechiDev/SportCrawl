## v0.6.0 (2026-07-09)

### Fix

- **core**: move type: ignore to correct line after E501 wrap

### Refactor

- **infra/persistence**: move scrape_queue table and enum to sch_infra schema

## v0.5.0 (2026-07-08)

### Feat

- **browser**: add Chrome extension with CF clearance capture and task fetch loop

### Fix

- **config,migrations**: reject ssl_mode=disable in prod and narrow env.py except to ImportError only

## v0.4.0 (2026-07-08)

### Feat

- **infra/work_server,cli**: add server and cli stubs
- **infra/browser**: add PydollEngine with lazy Chrome init and async context manager
- **infra/persistence**: add async session factory, ScrapeQueue model and Alembic migrations

### Fix

- **infra/migrations**: suppress Pyright reportUnusedImport on side-effect model import
- **infra**: narrow bare except Exception to specific exception types
- **infra/browser**: use *_ signature in __aexit__ to silence Pyright unused-param diagnostic
- **infra/browser**: resolve mypy --strict errors in PydollEngine
- **infra/persistence**: align url/domain to Text and fix deprecated op.get_bind in downgrade

## v0.3.0 (2026-07-08)

### Feat

- **infra/work_server,cli**: add server and cli stubs
- **infra/browser**: add PydollEngine with lazy Chrome init and async context manager
- **infra/persistence**: add async session factory, ScrapeQueue model and Alembic migrations
- **infra/browser**: add ScrapingEngine ABC
- **core/base**: add base repository, scraper and service abstractions
- **config**: add settings with pydantic-settings and nested env support

### Fix

- **infra/migrations**: suppress Pyright reportUnusedImport on side-effect model import
- **infra**: narrow bare except Exception to specific exception types
- **infra/browser**: use *_ signature in __aexit__ to silence Pyright unused-param diagnostic
- **infra/browser**: resolve mypy --strict errors in PydollEngine
- **infra/persistence**: align url/domain to Text and fix deprecated op.get_bind in downgrade

## v0.2.0 (2026-07-07)

### Feat

- **core**: add types, logging and exception hierarchy

### Fix

- **core**: fix E501 line length violations in logging module
- **core**: add Literal types, log_level validation and strengthen test assertions
