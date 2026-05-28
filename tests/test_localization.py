"""Tests for Localization pipeline."""

import os
import json

import pytest

from tests.fixtures.create_fixtures import create_localization_xlsx
from scripts.localization import (
    XlsxToJson as LocXlsxToJson,
    UpdateOriginalToDrive,
    ConvertDriveToOutput,
)


class TestLocalizationXlsxToJson:
    """Localization XlsxToJson with synthetic fixtures."""

    def test_basic_conversion(self, tmp_path):
        xlsx_path = str(tmp_path / "localization.xlsx")
        create_localization_xlsx(xlsx_path, [
            {0: "ref1", "ID": "ui.button.ok", "번역": "확인"},
            {0: "ref2", "ID": "ui.button.cancel", "번역": "취소"},
        ])
        output_path = str(tmp_path / "localization.json")

        LocXlsxToJson(xlsx_path, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["ui.button.ok"] == "확인"
        assert data["ui.button.cancel"] == "취소"

    def test_output_keys_are_id_column(self, tmp_path):
        xlsx_path = str(tmp_path / "localization.xlsx")
        create_localization_xlsx(xlsx_path, [
            {0: "original_ref", "ID": "my.key", "번역": "값"},
        ])
        output_path = str(tmp_path / "localization.json")

        LocXlsxToJson(xlsx_path, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "my.key" in data
        assert "original_ref" not in data

    def test_leading_apostrophe_stripped(self, tmp_path):
        xlsx_path = str(tmp_path / "localization.xlsx")
        create_localization_xlsx(xlsx_path, [
            {0: "ref", "ID": "key", "번역": "\'quoted"},
        ])
        output_path = str(tmp_path / "localization.json")

        LocXlsxToJson(xlsx_path, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["key"] == "quoted"

    def test_deserialize_applied(self, tmp_path):
        xlsx_path = str(tmp_path / "localization.xlsx")
        create_localization_xlsx(xlsx_path, [
            {0: "ref", "ID": "key", "번역": "line1\\tline2"},
        ])
        output_path = str(tmp_path / "localization.json")

        LocXlsxToJson(xlsx_path, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["key"] == "line1\tline2"


class TestLocalizationUpdate:
    def test_update_not_supported(self):
        assert UpdateOriginalToDrive() == []

    def test_incremental_skips(self):
        errors, successes = ConvertDriveToOutput(drive_file_paths=[])
        assert errors == []
        assert successes == []


class TestLocalizationNumericTranslation:
    """Numeric value in 번역 column should be skipped."""

    def test_numeric_translation_skipped(self, tmp_path):
        xlsx_path = str(tmp_path / "localization.xlsx")
        create_localization_xlsx(xlsx_path, [
            {0: "ref1", "ID": "key.valid", "번역": "정상번역"},
            {0: "ref2", "ID": "key.numeric", "번역": 12345},
        ])
        output_path = str(tmp_path / "localization.json")

        LocXlsxToJson(xlsx_path, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "key.valid" in data
        assert "key.numeric" not in data


# ============================================================
# P3: load_cache_date multi-line file (P3-20)
# ============================================================


