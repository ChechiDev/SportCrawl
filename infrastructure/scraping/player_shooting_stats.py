"""Parser for FBRef player shooting stats table.

Extracts per-season shooting statistics from the stats_shooting table
on a player profile page.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Tag

from domains.player_stats.models import PlayerShootingStatsRawData

logger = logging.getLogger(__name__)

_TEAM_ID_RE = re.compile(r"/en/squads/([a-f0-9]{8})/")
_COMP_PREFIX_RE = re.compile(r"^\d+\.\s*")


def _text(cell: Tag | None) -> str:
    if cell is None:
        return ""
    return cell.get_text(strip=True)


def _int(cell: Tag | None) -> int:
    raw = _text(cell).replace(",", "")
    if not raw or raw == "-":
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _decimal(cell: Tag | None) -> Decimal:
    raw = _text(cell)
    if not raw or raw == "-":
        return Decimal("0.00")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("0.00")


def _href_path(cell: Tag | None, link_text: str | None = None) -> str | None:
    if cell is None:
        return None
    for a in cell.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        if link_text is not None and a.get_text(strip=True) != link_text:
            continue
        href = str(a["href"])
        parsed = urlparse(href)
        return parsed.path if parsed.path else href
    return None


def _find_cell(row: Tag, *data_stats: str) -> Tag | None:
    for stat in data_stats:
        cell = row.find("td", attrs={"data-stat": stat})
        if cell and isinstance(cell, Tag):
            return cell
        cell = row.find("th", attrs={"data-stat": stat})
        if cell and isinstance(cell, Tag):
            return cell
    return None


def parse_player_shooting_stats(
    html: str, player_id: str
) -> list[PlayerShootingStatsRawData]:
    """Parse the stats_shooting table from a FBRef player profile page.

    Args:
        html: Full HTML of the player profile page.
        player_id: FBRef player slug (8-char hex).

    Returns:
        List of PlayerShootingStatsRawData, one per parseable season row.
        Returns [] when the table is absent.
    """
    soup = BeautifulSoup(html, "lxml")

    tables: list[Tag] = [
        t
        for t in soup.find_all("table")
        if isinstance(t, Tag) and str(t.get("id", "")).startswith("stats_shooting")
    ]

    if not tables:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            if "stats_shooting" in comment:
                inner = BeautifulSoup(comment, "lxml")
                tables = [
                    t
                    for t in inner.find_all("table")
                    if isinstance(t, Tag)
                    and str(t.get("id", "")).startswith("stats_shooting")
                ]
                if tables:
                    break

    if not tables:
        return []

    results: list[PlayerShootingStatsRawData] = []

    for table in tables:
        tbody = table.find("tbody")
        if tbody is None or not isinstance(tbody, Tag):
            continue

        for row in tbody.find_all("tr"):
            if not isinstance(row, Tag):
                continue

            row_classes = row.get("class") or []
            if "thead" in row_classes or "spacer" in row_classes:
                continue

            season_cell = _find_cell(row, "year_id")
            season_text = _text(season_cell)
            if not season_text:
                continue

            try:
                parts = season_text.split("-")
                season = int(parts[-1]) if len(parts[-1]) == 4 else int(parts[0])
            except ValueError:
                logger.debug(
                    "player_shooting_stats: skipping row — unparseable season %r",
                    season_text,
                )
                continue

            team_cell = _find_cell(row, "team", "squad")
            squad_text = _text(team_cell)

            if "Clubs" in squad_text:
                continue

            team_url = _href_path(team_cell)
            if team_url is None:
                logger.debug(
                    "player_shooting_stats: no team URL for player %s season %s",
                    player_id,
                    season_text,
                )
                continue

            m = _TEAM_ID_RE.search(team_url)
            if not m:
                logger.debug(
                    "player_shooting_stats: cannot extract team_id from %r",
                    team_url,
                )
                continue
            fk_team = m.group(1)

            country_cell = _find_cell(row, "country")
            fk_country: str | None = None
            if country_cell and isinstance(country_cell, Tag):
                a = country_cell.find("a", href=True)
                if a and isinstance(a, Tag):
                    href = str(a["href"])
                    m_country = re.search(r"/en/country/([A-Z]{2,3})/", href)
                    if m_country:
                        fk_country = m_country.group(1)

            comp_cell = _find_cell(row, "comp_level", "comp")
            comp_raw = _text(comp_cell)
            comp_name = _COMP_PREFIX_RE.sub("", comp_raw).strip()
            comp_url = _href_path(comp_cell)

            match_url = _href_path(_find_cell(row, "matches"))

            try:
                row_data = PlayerShootingStatsRawData(
                    player_id=player_id,
                    season=season,
                    fk_team=fk_team,
                    fk_country=fk_country,
                    fk_comp=0,
                    min_per_90=_decimal(_find_cell(row, "minutes_90s")),
                    goals=_int(_find_cell(row, "goals")),
                    shots=_int(_find_cell(row, "shots")),
                    shots_on_target=_int(_find_cell(row, "shots_on_target")),
                    shots_on_target_pct=_decimal(
                        _find_cell(row, "shots_on_target_pct")
                    ),
                    shots_per_90=_decimal(_find_cell(row, "shots_per90")),
                    sot_per_90=_decimal(_find_cell(row, "shots_on_target_per90")),
                    goals_per_shot=_decimal(_find_cell(row, "goals_per_shot")),
                    goals_per_sot=_decimal(
                        _find_cell(row, "goals_per_shot_on_target")
                    ),
                    pk_scored=_int(_find_cell(row, "pens_made")),
                    pk_att=_int(_find_cell(row, "pens_att")),
                    team_url=team_url,
                    comp_url=comp_url,
                    match_url=match_url,
                    comp_name=comp_name,
                )
            except Exception as exc:
                logger.debug(
                    "player_shooting_stats: skipping row for player %s season %s — %s",
                    player_id,
                    season_text,
                    exc,
                )
                continue

            results.append(row_data)

    return results
