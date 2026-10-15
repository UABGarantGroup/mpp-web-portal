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


def fix_baltic_mojibake(text: str) -> str:
    """
    Detects and repairs Baltic characters corrupted by CP1252 / Latin-1 misdecoding of Windows-1257 bytes.
    e.g. 'Naujøjø metø diena' -> 'Naujųjų metų diena'
    Safe for genuine Scandinavian text (preserves Norwegian/Danish/Swedish letters).
    """
    if not text:
        return text
    # Support both true byte 0xD0 decoded as Latin-1 Eth (U+00D0) and visual surrogate U+0110
    cleaned = text.replace("\u0110", "\u00d0")
    # Signature Lithuanian mojibake sequences produced when Windows-1257 Baltic bytes are decoded as Latin-1:
    # ų -> ø, ė -> ë, ū -> û, Š -> Ð, š -> ð, Ž -> Þ, ž -> þ, į -> á, č -> è
    mojibake_lithuanian_tokens = (
        "øjø", "metø", "atkûrimo", "Ðv.", "ðv.", "Velykø", "valstybës",
        "Tarptautinë", "Tëvo", "Joniniø", "Tautiðkos", "giesmës", "karûnavimo",
        "Þolinë", "Mergelës", "ëmimo", "dangø", "Visø", "Ðventøjø", "Mirusiøjø",
        "Vëliniø", "Kûèiø", "Kalëdø",
    )
    if any(token in cleaned for token in mojibake_lithuanian_tokens):
        try:
            return cleaned.encode("latin1").decode("windows-1257")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text



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
            "name": fix_baltic_mojibake(name),
            "from_date": d,
            "to_date": d,
            "working": False,
        })
    return items

