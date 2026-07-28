"""Parser for FBRef player standard stats table.

Extracts per-season standard statistics from the stats_standard table
on a player profile page.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Tag

from domains.player_stats.models import PlayerStdStatsRawData

logger = logging.getLogger(__name__)

_TEAM_ID_RE = re.compile(r"/en/squads/([a-f0-9]{8})/")
_COMP_PREFIX_RE = re.compile(r"^\d+\.\s*")


def _text(cell: Tag | None) -> str:
    """Return stripped text from a cell, or empty string."""
    if cell is None:
        return ""
    return cell.get_text(strip=True)


def _int(cell: Tag | None) -> int:
    """Parse an integer from a table cell. Returns 0 on missing/empty/dash."""
    raw = _text(cell).replace(",", "")
    if not raw or raw == "-":
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _decimal(cell: Tag | None) -> Decimal:
    """Parse a Decimal from a table cell. Returns Decimal('0.00') on failure."""
    raw = _text(cell)
    if not raw or raw == "-":
        return Decimal("0.00")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("0.00")


def _href_path(cell: Tag | None, link_text: str | None = None) -> str | None:
    """Extract the path portion of the first <a> href in a cell.

    When link_text is given, only anchors whose text matches are considered;
    otherwise the first anchor is used.
    """
    if cell is None:
        return None
    for a in cell.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        if link_text is not None and a.get_text(strip=True) != link_text:
            continue
        href = str(a["href"])
        parsed = urlparse(href)
        # Return path only; strip domain when absolute
        return parsed.path if parsed.path else href
    return None


def _find_cell(row: Tag, *data_stats: str) -> Tag | None:
    """Return first cell matching any of the given data-stat attributes."""
    for stat in data_stats:
        cell = row.find("td", attrs={"data-stat": stat})
        if cell and isinstance(cell, Tag):
            return cell
        # also check th (some tables use th for row headers)
        cell = row.find("th", attrs={"data-stat": stat})
        if cell and isinstance(cell, Tag):
            return cell
    return None


def parse_player_std_stats(html: str, player_id: str) -> list[PlayerStdStatsRawData]:
    """Parse the stats_standard table from a FBRef player profile page.

    Args:
        html: Full HTML of the player profile page.
        player_id: FBRef player slug (8-char hex).

    Returns:
        List of PlayerStdStatsRawData, one per parseable season row.
        Returns [] when the table is absent.
    """
    soup = BeautifulSoup(html, "lxml")

    # FBRef splits standard stats across multiple tables by competition type:
    # stats_standard_expanded, stats_standard_nat_tm, stats_standard_dom_lg, etc.
    # Also check inside HTML comments for tables not yet revealed by JS.
    tables: list[Tag] = [
        t for t in soup.find_all("table")
        if isinstance(t, Tag) and str(t.get("id", "")).startswith("stats_standard")
    ]

    if not tables:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            if "stats_standard" in comment:
                inner = BeautifulSoup(comment, "lxml")
                tables = [
                    t for t in inner.find_all("table")
                    if isinstance(t, Tag)
                    and str(t.get("id", "")).startswith("stats_standard")
                ]
                if tables:
                    break

    if not tables:
        return []

    results: list[PlayerStdStatsRawData] = []

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
                    "player_std_stats: skipping row — unparseable season %r",
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
                    "player_std_stats: skipping row — no team URL"
                    " for player %s season %s",
                    player_id,
                    season_text,
                )
                continue

            m = _TEAM_ID_RE.search(team_url)
            if not m:
                logger.debug(
                    "player_std_stats: skipping row — cannot extract team_id from %r",
                    team_url,
                )
                continue
            fk_team = m.group(1)

            country_cell = _find_cell(row, "country")
            fk_country: str | None = None
            if country_cell and isinstance(country_cell, Tag):
                # Country code is in the href: /en/country/ESP/Spain-Football
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

            age_cell = _find_cell(row, "age")
            age_text = _text(age_cell)
            age = 0
            if age_text and age_text != "-":
                try:
                    age = int(age_text.split("-")[0])
                except ValueError:
                    age = 0

            matches_cell = _find_cell(row, "games")
            match_url = _href_path(_find_cell(row, "matches"))

            try:
                row_data = PlayerStdStatsRawData(
                    player_id=player_id,
                    season=season,
                    fk_team=fk_team,
                    fk_country=fk_country,
                    fk_comp=0,
                    age=age,
                    matches=_int(matches_cell),
                    starts=_int(_find_cell(row, "games_starts")),
                    minutes=_int(_find_cell(row, "minutes")),
                    min_per_90=_decimal(_find_cell(row, "minutes_90s")),
                    goals=_int(_find_cell(row, "goals")),
                    assists=_int(_find_cell(row, "assists")),
                    goals_assists=_int(_find_cell(row, "goals_assists")),
                    goals_pk=_int(_find_cell(row, "goals_pens", "goals_pk")),
                    pk_scored=_int(_find_cell(row, "pens_made")),
                    pk_att=_int(_find_cell(row, "pens_att")),
                    yellow_cards=_int(_find_cell(row, "cards_yellow")),
                    red_cards=_int(_find_cell(row, "cards_red")),
                    goals_p90=_decimal(_find_cell(row, "goals_per90")),
                    assists_p90=_decimal(_find_cell(row, "assists_per90")),
                    goals_assists_p90=_decimal(_find_cell(row, "goals_assists_per90")),
                    goals_pk_p90=_decimal(
                        _find_cell(row, "goals_pens_per90", "goals_pk_per90")
                    ),
                    goals_assists_pk_p90=_decimal(
                        _find_cell(
                            row, "goals_assists_pens_per90", "goals_assists_pk_per90"
                        )
                    ),
                    team_url=team_url,
                    comp_id=comp_id,
                    match_url=match_url,
                    comp_name=comp_name,
                )
            except Exception as exc:
                logger.debug(
                    "player_std_stats: skipping row for player %s season %s — %s",
                    player_id,
                    season_text,
                    exc,
                )
                continue

            results.append(row_data)

    return results
