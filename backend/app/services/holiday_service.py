"""
Holiday import service leveraging python 'holidays' library.
Provides multi-country public holidays for MS Project base calendar generation.
"""

from datetime import date
from typing import Dict, List, Optional
import holidays


def get_supported_countries() -> Dict[str, str]:
    """
    Returns a dictionary of country code to country name.
    """
    # Common European & international enterprise country codes
    return {
        "LT": "Lithuania",
        "LV": "Latvia",
        "EE": "Estonia",
        "PL": "Poland",
        "DE": "Germany",
        "NO": "Norway",
        "SE": "Sweden",
        "FI": "Finland",
        "DK": "Denmark",
        "NL": "Netherlands",
        "GB": "United Kingdom",
        "US": "United States",
    }


def fetch_country_holidays(
    country_code: str = "LT",
    years: Optional[List[int]] = None
) -> List[Dict[str, any]]:
    """
    Retrieves public holidays for specified country and years.
    Returns list of dicts: [{"date": date_obj, "name": str, "working": False}]
    """
    if not years:
        current_year = date.today().year
        years = [current_year, current_year + 1]

    country_code = country_code.upper()
    try:
        h_obj = holidays.country_holidays(country_code, years=years)
    except NotImplementedError:
        # Fallback to Lithuania if unsupported
        h_obj = holidays.country_holidays("LT", years=years)

    items = []
    for d, name in sorted(h_obj.items()):
        items.append({
            "name": name,
            "from_date": d,
            "to_date": d,
            "working": False,
        })
    return items
