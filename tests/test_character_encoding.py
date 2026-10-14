"""
Tests for Baltic and international character encoding, mojibake prevention,
and MS SQL Server Unicode column mappings.
"""

import pytest
from sqlalchemy import String, Text
from sqlalchemy.dialects import mssql, postgresql, sqlite

from backend.app.services.holiday_service import fix_baltic_mojibake


def test_fix_baltic_mojibake_repairs_corrupted_lithuanian_strings():
    """Verifies that Lithuanian strings corrupted by Windows-1257 / CP1252 mismatch are restored to UTF-8."""
    corrupted_to_expected = {
        "Naujøjø metø diena": "Naujųjų metų diena",
        "Lietuvos valstybës atkûrimo diena": "Lietuvos valstybės atkūrimo diena",
        "Lietuvos nepriklausomybës atkûrimo diena": "Lietuvos nepriklausomybės atkūrimo diena",
        "Đv. Velykos": "Šv. Velykos",
        "Antroji ðv. Velykø diena": "Antroji šv. Velykų diena",
        "Tarptautinë darbo diena": "Tarptautinė darbo diena",
        "Tëvo diena": "Tėvo diena",
        "Rasos ir Joniniø diena": "Rasos ir Joninių diena",
        "Þolinë (Ðvè. Mergelës Marijos ëmimo á dangø diena)": "Žolinė (Švč. Mergelės Marijos ėmimo į dangų diena)",
        "Visø Ðventøjø diena": "Visų Šventųjų diena",
        "Mirusiøjø atminimo (Vëliniø) diena": "Mirusiųjų atminimo (Vėlinių) diena",
        "Kûèiø diena": "Kūčių diena",
        "Ðv. Kalëdø pirma diena": "Šv. Kalėdų pirma diena",
        "Ðv. Kalëdø antra diena": "Šv. Kalėdų antra diena",
    }

    for corrupted, expected in corrupted_to_expected.items():
        assert fix_baltic_mojibake(corrupted) == expected


def test_fix_baltic_mojibake_preserves_norwegian_and_clean_utf8():
    """Verifies that genuine Scandinavian text and already clean UTF-8 strings are not altered."""
    clean_strings = [
        "Naujųjų metų diena",
        "Lietuvos valstybės atkūrimo diena",
        "Šv. Velykos",
        "Første nyttårsdag",
        "Skjærtorsdag",
        "Langfredag",
        "Første påskedag",
        "Andre påskedag",
        "Standard English Name",
    ]

    for s in clean_strings:
        assert fix_baltic_mojibake(s) == s


def test_mssql_string_compiles_to_nvarchar():
    """Verifies that SQLAlchemy String and Text types compile to NVARCHAR on MS SQL Server to prevent mojibake."""
    d_mssql = mssql.dialect()
    assert "NVARCHAR(255)" in String(255).compile(dialect=d_mssql)
    assert "NVARCHAR(MAX)" in String().compile(dialect=d_mssql)
    assert "NVARCHAR(MAX)" in Text().compile(dialect=d_mssql)


def test_sqlite_and_postgres_compilation_unaffected():
    """Verifies that SQLite and PostgreSQL continue using standard VARCHAR and TEXT."""
    d_sqlite = sqlite.dialect()
    d_pg = postgresql.dialect()

    assert "VARCHAR(255)" in String(255).compile(dialect=d_sqlite)
    assert "VARCHAR(255)" in String(255).compile(dialect=d_pg)
    assert "TEXT" in Text().compile(dialect=d_sqlite)
    assert "TEXT" in Text().compile(dialect=d_pg)
