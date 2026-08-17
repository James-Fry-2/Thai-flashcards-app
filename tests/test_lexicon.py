"""
Tests for scripts/ingest_lexicon.py column mapping and src/db/services/lexicon_service.py.

Run inside the container (or with .venv activated + PYTHONPATH=/app):
    pytest tests/test_lexicon.py -v
"""
import pytest
from unittest.mock import MagicMock

_HEADER_ROW_1 = (
    "VOLUBILIS Database", None, None, "v. 26.2 (Jul. 2026)", "114577 entr.",
    None, None, None, None, None, None, None, None, None, None,
)
_HEADER_ROW_2 = (
    "THAIROM", "EASYTHAI", "THAIPHON", "ETYMO", "THA (Thai)", "ENG (English)",
    "FRA (French)", "TYPE", "USAGE", "SCIENT/abbrev.", "DOM", "CLASSIF",
    "SYLLAB", "NOTE", "SYN",
)


def _make_workbook(tmp_path, rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADER_ROW_1)
    ws.append(_HEADER_ROW_2)
    for row in rows:
        ws.append(row)
    path = tmp_path / "test_volubilis.xlsx"
    wb.save(path)
    return str(path)


class TestParseRows:
    """Regression coverage for the column-index mapping — a wrong index here
    is exactly what caused the original data-loss incident, so these assert
    against the file's real header shape."""

    def test_scientific_binomial_routed_to_scientific_name_not_english(self, tmp_path):
        """The real รัก entry: SCIENT/abbrev. carries the binomial (with a
        trailing authorship abbreviation) and the ENG cell also repeats the
        bare binomial as one of its semicolon-split senses. Neither should
        surface as an `english` row — only as `scientific_name` on the
        sibling common-name sense from the same source row."""
        from scripts.ingest_lexicon import _parse_rows

        source_file = _make_workbook(tmp_path, [
            ("rak", "rak", "¯rak", None, "รัก",
             "Calotropis gigantea ; Crown flower", "arbre à laque [m]",
             "n.", None, "Calotropis gigantea R. Br.", None, None, None, None, None),
            ("rak", "rak", "¯rak", None, "รัก",
             "lacquer", "laque de Chine [f]", "n.", None, None, None, None, None, None, None),
            ("rak", "rak", "¯rak", None, "รัก",
             "love ; be fond of ; like", "aimer", "v.", None, None, "VAL", None, "[รัก]", None, None),
        ])

        rows = list(_parse_rows(source_file))
        englishes = [r["english"] for r in rows]

        assert "Calotropis gigantea" not in englishes
        assert "Crown flower" in englishes
        assert "lacquer" in englishes
        assert "love" in englishes
        assert "like" in englishes

        crown = next(r for r in rows if r["english"] == "Crown flower")
        assert crown["scientific_name"] == "Calotropis gigantea"

        lacquer = next(r for r in rows if r["english"] == "lacquer")
        assert lacquer["scientific_name"] is None

    def test_level_always_none_for_this_edition(self, tmp_path):
        """The VOLUBILIS DATABASE edition has no per-row Level column —
        ingestion must not fabricate one."""
        from scripts.ingest_lexicon import _parse_rows

        source_file = _make_workbook(tmp_path, [
            ("nam", "nam", "´nam", None, "น้ำ", "water", "eau [f]",
             "n.", None, None, None, None, None, None, None),
        ])

        rows = list(_parse_rows(source_file))
        assert rows[0]["level"] is None

    def test_usage_marker_stripped_of_parens(self, tmp_path):
        from scripts.ingest_lexicon import _parse_rows

        source_file = _make_workbook(tmp_path, [
            ("x", "x", "x", None, "ทดสอบ", "archaic term",
             None, "n.", "(obsol.)", None, None, None, None, None, None),
        ])

        rows = list(_parse_rows(source_file))
        assert rows[0]["usage"] == "obsol."

    def test_no_usage_or_scientific_name_leaves_fields_none(self, tmp_path):
        from scripts.ingest_lexicon import _parse_rows

        source_file = _make_workbook(tmp_path, [
            ("nam", "nam", "´nam", None, "น้ำ", "water", "eau [f]",
             "n.", None, None, None, None, None, None, None),
        ])

        rows = list(_parse_rows(source_file))
        assert rows[0]["usage"] is None
        assert rows[0]["scientific_name"] is None


class TestLookup:
    """lookup() is unchanged, but since ingestion now routes binomials to
    scientific_name instead of english, it should stop returning them —
    verified here at the service layer with a mocked db.execute."""

    @pytest.mark.asyncio
    async def test_lookup_excludes_scientific_names(self):
        from src.db.services import lexicon_service

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("Crown flower",), ("lacquer",), ("love",), ("like",),
        ]
        mock_db.execute = _async_return(mock_result)

        translations = await lexicon_service.lookup(mock_db, "รัก")
        assert "Calotropis gigantea" not in translations
        assert translations == ["Crown flower", "lacquer", "love", "like"]


class TestLookupRanked:
    @pytest.mark.asyncio
    async def test_returns_level_and_pos(self):
        from src.db.services import lexicon_service

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("Crown flower", None, "n."),
            ("love", "B", "v."),
            ("like", "B", "v."),
        ]
        mock_db.execute = _async_return(mock_result)

        senses = await lexicon_service.lookup_ranked(mock_db, "รัก")
        assert senses == [
            {"english": "Crown flower", "level": None, "pos": "n."},
            {"english": "love", "level": "B", "pos": "v."},
            {"english": "like", "level": "B", "pos": "v."},
        ]

    @pytest.mark.asyncio
    async def test_dedupes_by_english(self):
        from src.db.services import lexicon_service

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("love", "B", "v."),
            ("love", "B", "v."),
        ]
        mock_db.execute = _async_return(mock_result)

        senses = await lexicon_service.lookup_ranked(mock_db, "รัก")
        assert len(senses) == 1


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn
