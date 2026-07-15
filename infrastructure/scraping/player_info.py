"""PlayerInfoScraper — parses FBRef player profile pages.

HTML structure (from live FBRef inspection):

  <div id="info" class="players open">
    <div id="meta">
      <h1><span>Player Name</span></h1>
      <p><strong>Position:</strong> FW-MF (AM, right) •
         <strong>Footed:</strong> Left</p>
      <p><span>180cm</span>,&nbsp;<span>76kg</span>&nbsp;...</p>
      <p>
        <strong>Born:</strong>
        <span id="necro-birth" data-birth="2007-07-13"> July 13, 2007 </span>
        ... in Mataró, Spain
        <span class="f-i" style="background-image:url('.../es-2007.svg')"> </span>
      </p>
      <p><strong>Wages</strong> ". " <a href="#all_wages">...</a>
         " Expires June 2031. Via "</p>
    </div>
  </div>

All fields optional — missing fields yield None, never raise.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from domains.player_info.models import PlayerInfoPage, PlayerInfoRawData

logger = logging.getLogger(__name__)

_HEIGHT_RE = re.compile(r"(\d+)\s*cm", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"(\d+)\s*kg", re.IGNORECASE)
_WAGES_RE = re.compile(r"£([\d,]+)")
_EXPIRES_RE = re.compile(
    r"Expires\s+"
    r"(January|February|March|April|May|June"
    r"|July|August|September|October|November|December)"
    r"\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _meta_div(soup: BeautifulSoup | Tag) -> Tag | None:
    info = soup.find("div", id="info")
    if info and isinstance(info, Tag):
        meta = info.find("div", id="meta")
        if meta and isinstance(meta, Tag):
            return meta
    return None


def _parse_positions(
    soup: BeautifulSoup | Tag,
) -> tuple[str | None, str | None, str | None]:
    """Extract position codes from the Position label paragraph."""
    for p in soup.find_all("p"):
        strong = p.find("strong")
        if not strong or "position" not in strong.get_text(strip=True).lower():
            continue
        text = p.get_text(separator=" ", strip=True)
        # Strip the strong label text, take only the position code part before "("
        after_label = re.sub(r"Position\s*:?\s*", "", text, flags=re.IGNORECASE)
        # "FW-MF (AM, right) • Footed: Left" → take up to first "(" or "•"
        pos_part = re.split(r"[•(]", after_label)[0].strip()
        # Split on "-" and clean
        parts = [
            c.strip().upper()
            for c in pos_part.split("-")
            if c.strip() and c.strip().isalpha()
        ]
        return (
            parts[0] if len(parts) > 0 else None,
            parts[1] if len(parts) > 1 else None,
            parts[2] if len(parts) > 2 else None,
        )
    return None, None, None


def _parse_foot(soup: BeautifulSoup | Tag) -> str | None:
    """Extract foot preference from the Footed label."""
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        m = re.search(r"Footed\s*:?\s*(\w+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_height_weight(soup: BeautifulSoup | Tag) -> tuple[int | None, int | None]:
    """Extract height (cm) and weight (kg) from the span-based paragraph."""
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        mh = _HEIGHT_RE.search(text)
        mw = _WEIGHT_RE.search(text)
        if mh or mw:
            height = int(mh.group(1)) if mh else None
            weight = int(mw.group(1)) if mw else None
            return height, weight
    return None, None


def _parse_birth(soup: BeautifulSoup | Tag) -> tuple[date | None, str | None]:
    """Extract birth date and city from the necro-birth span."""
    player_born: date | None = None
    city_name: str | None = None

    birth_span = soup.find("span", id="necro-birth")
    if birth_span and isinstance(birth_span, Tag):
        data_birth = birth_span.get("data-birth")
        if data_birth:
            try:
                parts = str(data_birth).split("-")
                player_born = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass

        # City comes after "in" in the born paragraph: "... ) in Mataró, Spain"
        parent = birth_span.find_parent("p")
        if parent and isinstance(parent, Tag):
            full_text = parent.get_text(separator=" ", strip=True)
            # Match "in <City>" — the city ends at a comma or end of meaningful text
            m = re.search(
                r"\bin\s+([\w\s\-áéíóúàèìòùäëïöüñçÁÉÍÓÚÀÈÌÒÙÄËÏÖÜÑÇ]+?)"
                r"(?:\s*,|\s*$)",
                full_text,
            )
            if m:
                city_name = m.group(1).strip() or None

    return player_born, city_name


def _parse_country_birth_name(soup: BeautifulSoup | Tag) -> str | None:
    """Extract birth country name from 'in City, Country' text near necro-birth span."""
    birth_span = soup.find("span", id="necro-birth")
    if not birth_span or not isinstance(birth_span, Tag):
        return None
    parent = birth_span.find_parent("p")
    if not parent or not isinstance(parent, Tag):
        return None
    full_text = parent.get_text(separator=" ", strip=True).strip()
    def _clean(raw: str) -> str | None:
        cleaned = re.sub(r"\s+[a-z]{2}$", "", raw.strip())
        return cleaned or None

    m = re.search(r"\bin\s+[^,]+,\s*([A-Za-z\s\-]+)", full_text)
    if m:
        return _clean(m.group(1))
    # Fallback: "in <Country>" with no city
    m2 = re.search(r"\bin\s+([A-Za-z\s\-]+)", full_text)
    if m2:
        return _clean(m2.group(1))
    return None


def _parse_national_team_name(soup: BeautifulSoup | Tag) -> str | None:
    """Extract national team country name from the National Team paragraph."""
    for strong in soup.find_all("strong"):
        if "National Team" in strong.get_text():
            p = strong.find_parent("p")
            if p and isinstance(p, Tag):
                a = p.find("a", href=re.compile(r"^/en/country/"))
                if a and isinstance(a, Tag):
                    return a.get_text(strip=True) or None
    return None


def _parse_wages_expires(soup: BeautifulSoup | Tag) -> tuple[int | None, date | None]:
    """Extract weekly wages (£) and contract expiry date."""
    player_wages: int | None = None
    player_expires: date | None = None

    for p in soup.find_all("p"):
        strong = p.find("strong")
        if not strong or "wages" not in strong.get_text(strip=True).lower():
            continue
        text = p.get_text(separator=" ", strip=True)

        mw = _WAGES_RE.search(text)
        if mw:
            try:
                player_wages = int(mw.group(1).replace(",", ""))
            except ValueError:
                pass

        me = _EXPIRES_RE.search(text)
        if me:
            month = _MONTHS.get(me.group(1).lower())
            year = int(me.group(2))
            if month:
                try:
                    player_expires = date(year, month, 1)
                except ValueError:
                    pass
        break

    return player_wages, player_expires


def _parse_photo(soup: BeautifulSoup | Tag) -> str | None:
    """Extract player photo URL."""
    img = soup.find("img", id="player_photo")
    if img and isinstance(img, Tag):
        src = img.get("src")
        if src:
            return str(src)
    return None


class PlayerInfoScraper:
    """Scraper for FBRef player profile pages.

    Pure parsing — no database calls, no network I/O. Instantiated per player.
    """

    def __init__(self, player_id: str, player_info_url: str) -> None:
        self._player_id = player_id
        self._player_info_url = player_info_url

    async def parse(self, html: str) -> PlayerInfoPage:
        soup = BeautifulSoup(html, "lxml")

        # Scope parsing to div#info > div#meta when available
        meta = _meta_div(soup)
        scope: BeautifulSoup | Tag = meta if meta is not None else soup

        position_1, position_2, position_3 = _parse_positions(scope)
        player_foot = _parse_foot(scope)
        player_height, player_weight = _parse_height_weight(scope)
        player_born, city_name = _parse_birth(scope)
        country_birth_name = _parse_country_birth_name(scope)
        national_team_name = _parse_national_team_name(scope)
        player_wages, player_expires = _parse_wages_expires(scope)
        photo_url = _parse_photo(soup)

        raw = PlayerInfoRawData(
            player_id=self._player_id,
            player_info_url=self._player_info_url,
            fk_country_birth=None,
            country_birth_name=country_birth_name,
            national_team_name=national_team_name,
            fk_national_team=None,
            city_name=city_name,
            player_born=player_born,
            player_height=player_height,
            player_weight=player_weight,
            position_1=position_1,
            position_2=position_2,
            position_3=position_3,
            player_foot=player_foot,
            player_wages=player_wages,
            player_expires=player_expires,
            photo_url=photo_url,
        )
        return PlayerInfoPage(players=[raw])
