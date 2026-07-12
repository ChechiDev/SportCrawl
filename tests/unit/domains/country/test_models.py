"""Unit tests for CountryRawData and CountryPage domain models."""

import pytest
from pydantic import ValidationError

from domains.country.models import CountryPage, CountryRawData

_FLAG_CDN = "https://cdn.fbref.com/req/202301010/images/flags"


# ---------------------------------------------------------------------------
# CountryRawData — valid construction
# ---------------------------------------------------------------------------


def test_country_raw_data_valid_full() -> None:
    c = CountryRawData(
        country_id="ENG",
        country_name="England",
        country_url="/en/country/ENG/England-Football",
        confederation="UEFA",
        flag_id="gb",
        flag_url=f"{_FLAG_CDN}/gb.gif",
    )
    assert c.country_id == "ENG"
    assert c.country_name == "England"
    assert c.country_url == "/en/country/ENG/England-Football"
    assert c.confederation == "UEFA"
    assert c.flag_id == "gb"
    assert c.flag_url == f"{_FLAG_CDN}/gb.gif"


def test_country_raw_data_confederation_optional() -> None:
    c = CountryRawData(
        country_id="AFG",
        country_name="Afghanistan",
        country_url="/en/country/AFG/Afghanistan-Football",
        flag_id="af",
        flag_url=f"{_FLAG_CDN}/af.gif",
    )
    assert c.confederation is None


def test_country_raw_data_country_id_two_chars() -> None:
    c = CountryRawData(
        country_id="FR",
        country_name="France",
        country_url="/en/country/FR/France-Football",
        flag_id="fr",
        flag_url=f"{_FLAG_CDN}/fr.gif",
    )
    assert c.country_id == "FR"


def test_country_raw_data_country_id_three_chars() -> None:
    c = CountryRawData(
        country_id="ALG",
        country_name="Algeria",
        country_url="/en/country/ALG/Algeria-Football",
        flag_id="dz",
        flag_url=f"{_FLAG_CDN}/dz.gif",
    )
    assert c.country_id == "ALG"


# ---------------------------------------------------------------------------
# CountryRawData — validation errors
# ---------------------------------------------------------------------------


_ENG_URL = "/en/country/ENG/England-Football"
_ENG_FLAG = f"{_FLAG_CDN}/gb.gif"


def test_country_raw_data_missing_country_name_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(  # type: ignore[call-arg]
            country_id="ENG", country_url=_ENG_URL,
            flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_missing_country_url_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(  # type: ignore[call-arg]
            country_id="ENG", country_name="England",
            flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_missing_flag_id_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(  # type: ignore[call-arg]
            country_id="ENG", country_name="England",
            country_url=_ENG_URL, flag_url=_ENG_FLAG,
        )


def test_country_raw_data_missing_flag_url_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(  # type: ignore[call-arg]
            country_id="ENG", country_name="England",
            country_url=_ENG_URL, flag_id="gb",
        )


def test_country_raw_data_missing_country_id_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(  # type: ignore[call-arg]
            country_name="England", country_url=_ENG_URL,
            flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_country_id_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="E", country_name="England",
            country_url="/en/country/E/England-Football",
            flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_country_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="ENGL", country_name="England",
            country_url="/en/country/ENGL/England-Football",
            flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_country_name_empty_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="ENG", country_name="",
            country_url=_ENG_URL, flag_id="gb", flag_url=_ENG_FLAG,
        )


def test_country_raw_data_flag_id_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="ENG", country_name="England",
            country_url=_ENG_URL,
            flag_id="g", flag_url=f"{_FLAG_CDN}/g.gif",
        )


def test_country_raw_data_flag_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="ENG", country_name="England",
            country_url=_ENG_URL,
            flag_id="gbr", flag_url=f"{_FLAG_CDN}/gbr.gif",
        )


def test_country_raw_data_flag_url_empty_raises() -> None:
    with pytest.raises(ValidationError):
        CountryRawData(
            country_id="ENG", country_name="England",
            country_url=_ENG_URL, flag_id="gb", flag_url="",
        )


# ---------------------------------------------------------------------------
# confederation — uppercase normalization
# ---------------------------------------------------------------------------


def test_confederation_normalised_to_uppercase() -> None:
    c = CountryRawData(
        country_id="ENG", country_name="England",
        country_url="/en/country/ENG/England-Football",
        confederation="uefa", flag_id="gb", flag_url=f"{_FLAG_CDN}/gb.gif",
    )
    assert c.confederation == "UEFA"


def test_confederation_mixed_case_normalised() -> None:
    c = CountryRawData(
        country_id="BRA", country_name="Brazil",
        country_url="/en/country/BRA/Brazil-Football",
        confederation="Conmebol", flag_id="br", flag_url=f"{_FLAG_CDN}/br.gif",
    )
    assert c.confederation == "CONMEBOL"


def test_confederation_none_preserved() -> None:
    c = CountryRawData(
        country_id="AFG", country_name="Afghanistan",
        country_url="/en/country/AFG/Afghanistan-Football",
        confederation=None, flag_id="af", flag_url=f"{_FLAG_CDN}/af.gif",
    )
    assert c.confederation is None


# ---------------------------------------------------------------------------
# CountryPage
# ---------------------------------------------------------------------------


def test_country_page_empty() -> None:
    page = CountryPage(countries=[])
    assert page.countries == []


def test_country_page_with_rows() -> None:
    rows = [
        CountryRawData(
            country_id="ENG", country_name="England",
            country_url="/en/country/ENG/England-Football",
            confederation="UEFA", flag_id="gb", flag_url=f"{_FLAG_CDN}/gb.gif",
        ),
        CountryRawData(
            country_id="AFG", country_name="Afghanistan",
            country_url="/en/country/AFG/Afghanistan-Football",
            confederation="AFC", flag_id="af", flag_url=f"{_FLAG_CDN}/af.gif",
        ),
    ]
    page = CountryPage(countries=rows)
    assert len(page.countries) == 2
    assert page.countries[0].country_id == "ENG"
    assert page.countries[1].flag_id == "af"
