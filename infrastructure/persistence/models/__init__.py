"""ORM models package. Import Base and all model classes from here."""

from infrastructure.persistence.models.base import Base
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

__all__ = ["Base", "ScrapeQueue", "ScrapeStatus"]
