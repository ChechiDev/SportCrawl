"""Parser for FBRef player playing time stats table.

Extracts per-season playing time statistics from stats_playing_time tables
on a player profile page (e.g. stats_playing_time_dom_lg, stats_playing_time_nat_tm).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Tag

from domains.player_stats.models import PlayerPlayingTimeStatsRawData

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


def parse_player_playing_time_stats(
    html: str, player_id: str
) -> list[PlayerPlayingTimeStatsRawData]:
    """Parse stats_playing_time tables from a FBRef player profile page.

    Args:
        html: Full HTML of the player profile page.
        player_id: FBRef player slug (8-char hex).

    Returns:
        List of PlayerPlayingTimeStatsRawData, one per parseable season row.
        Returns [] when the table is absent.
    """
    soup = BeautifulSoup(html, "lxml")

    tables: list[Tag] = [
        t
        for t in soup.find_all("table")
        if isinstance(t, Tag) and str(t.get("id", "")).startswith("stats_playing_time")
    ]

    if not tables:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            if "stats_playing_time" in comment:
                inner = BeautifulSoup(comment, "lxml")
                tables = [
                    t
                    for t in inner.find_all("table")
                    if isinstance(t, Tag)
                    and str(t.get("id", "")).startswith("stats_playing_time")
                ]
                if tables:
                    break

    if not tables:
        return []

    results: list[PlayerPlayingTimeStatsRawData] = []

    for table in tables:
        tbody = table.find("tbody")
        if tbody is None or not isinstance(tbody, Tag):
            continue

        for row in tbody.find_all("tr"):
            if not isinstance(row, Tag):
                continue

            row_classes: list[str] = list(row.get("class") or [])
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
                    "player_playing_time_stats: skipping row — unparseable season %r",
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
                    "player_playing_time_stats: no team URL for player %s season %s",
                    player_id,
                    season_text,
                )
                continue

            m = _TEAM_ID_RE.search(team_url)
            if not m:
                logger.debug(
                    "player_playing_time_stats: cannot extract team_id from %r",
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
            comp_id: int | None = None
            _comp_href = _href_path(comp_cell)
            if _comp_href:
                _m_comp = re.search(r"/en/comps/(\d+)/", _comp_href)
                if _m_comp:
                    comp_id = int(_m_comp.group(1))

            match_url = _href_path(_find_cell(row, "matches"))

            try:
                row_data = PlayerPlayingTimeStatsRawData(
                    player_id=player_id,
                    season=season,
                    fk_team=fk_team,
                    fk_country=fk_country,
                    fk_comp=0,
                    matches=_int(_find_cell(row, "games")),
                    minutes=_int(_find_cell(row, "minutes")),
                    min_per_match=_decimal(_find_cell(row, "minutes_per_game")),
                    min_pct=_decimal(_find_cell(row, "minutes_pct")),
                    min_per_90=_decimal(_find_cell(row, "minutes_90s")),
                    starts=_int(_find_cell(row, "games_starts")),
                    min_per_start=_decimal(_find_cell(row, "minutes_per_start")),
                    games_complete=_int(_find_cell(row, "games_complete")),
                    subs=_int(_find_cell(row, "games_subs")),
                    min_per_sub=_decimal(_find_cell(row, "minutes_per_sub")),
                    unused_sub=_int(_find_cell(row, "unused_subs")),
                    ppm=_decimal(_find_cell(row, "points_per_game")),
                    on_goals_for=_int(_find_cell(row, "on_goals_for")),
                    on_goals_against=_int(_find_cell(row, "on_goals_against")),
                    plus_minus=_int(_find_cell(row, "plus_minus")),
                    plus_minus_per90=_decimal(_find_cell(row, "plus_minus_per90")),
                    on_off=_decimal(_find_cell(row, "on_off")),
                    team_url=team_url,
                    comp_id=comp_id,
                    match_url=match_url,
                    comp_name=comp_name,
                )
            except Exception as exc:
                logger.debug(
                    "player_playing_time_stats: skipping row for player %s"
                    " season %s — %s",
                    player_id,
                    season_text,
                    exc,
                )
                continue

            results.append(row_data)

    return results
