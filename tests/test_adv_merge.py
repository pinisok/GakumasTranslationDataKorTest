"""Tests for adv_merge module — merge/diff/conversion logic."""

import os
from io import StringIO

import pandas as pd
import pytest

from tests.fixtures.create_fixtures import create_adv_xlsx, create_adv_txt
from scripts.adv_merge import (
    _internalTxtToScv,
    _internalCsvToDataFrame,
    _internalUpdateDataFrame,
    _internalDataFrameToXlsx,
    _replace_at_offset,
    _internalCsvToTxt,
)


# ============================================================
# _replace_at_offset
# ============================================================


class TestReplaceAtOffset:
    def test_basic_replacement(self):
        text = "hello world hello"
        result, offset = _replace_at_offset(text, "hello", "HI", 0)
        assert result == "HI world hello"
        assert offset == 2

    def test_offset_skips_first_occurrence(self):
        text = "hello world hello"
        result, offset = _replace_at_offset(text, "hello", "HI", 3)
        assert result == "hello world HI"
        assert offset == 14

    def test_not_found_raises(self):
        with pytest.raises(ValueError, match="Could not find"):
            _replace_at_offset("hello", "xyz", "abc", 0)

    def test_offset_beyond_match_raises(self):
        with pytest.raises(ValueError, match="Could not find"):
            _replace_at_offset("hello world", "hello", "HI", 10)

    def test_empty_old_string(self):
        result, offset = _replace_at_offset("hello", "", "X", 0)
        assert result == "Xhello"
        assert offset == 1

    def test_replacement_longer_than_original(self):
        text = "ab"
        result, offset = _replace_at_offset(text, "a", "LONG", 0)
        assert result == "LONGb"
        assert offset == 4


# ============================================================
# _internalCsvToDataFrame
# ============================================================


class TestCsvToDataFrameEdgeCases:
    def test_empty_file_raises(self, tmp_path):
        """CSV with no messages should raise ValueError."""
        txt_path = str(tmp_path / "empty.txt")
        # Create a txt with only non-text tags (no message/narration/title)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("")
        # Manually create a CSV that would produce empty DataFrame after dropping tail
        csv_content = "id,name,text,trans\ninfo,test.txt,,\n译者,None,,\n"
        csv_fp = StringIO(csv_content)
        with pytest.raises(ValueError, match="No message"):
            _internalCsvToDataFrame(csv_fp)


# ============================================================
# _internalUpdateDataFrame edge cases
# ============================================================


class TestUpdateDataFrameEdgeCases:
    def test_all_rows_same_text_returns_original(self, tmp_path):
        """When all text matches, original DataFrame with translations is returned."""
        xlsx_path = str(tmp_path / "existing.xlsx")
        create_adv_xlsx(xlsx_path, [
            {"id": "0", "name": "A", "translated name": "에이",
             "text": "同じ", "translated text": "같음"},
            {"id": "0", "name": "B", "translated name": "비",
             "text": "同じ2", "translated text": "같음2"},
        ])

        new_df = pd.DataFrame([
            {"id": "0", "name": "A", "translated name": "",
             "text": "同じ", "translated text": ""},
            {"id": "0", "name": "B", "translated name": "",
             "text": "同じ2", "translated text": ""},
        ])

        with open(xlsx_path, "rb") as fp:
            result_df, warnings = _internalUpdateDataFrame(new_df, fp)

        records = result_df.to_dict(orient="records")
        assert records[0]["translated text"] == "같음"
        assert records[1]["translated text"] == "같음2"
        assert len(warnings) == 0

    def test_override_triggered_by_middle_row_change(self, tmp_path):
        """Text change in a non-first row should trigger override mode."""
        xlsx_path = str(tmp_path / "existing.xlsx")
        create_adv_xlsx(xlsx_path, [
            {"id": "0", "name": "A", "translated name": "",
             "text": "行1", "translated text": "줄1"},
            {"id": "0", "name": "B", "translated name": "",
             "text": "行2旧", "translated text": "줄2"},
        ])

        new_df = pd.DataFrame([
            {"id": "0", "name": "A", "translated name": "",
             "text": "行1", "translated text": ""},
            {"id": "0", "name": "B", "translated name": "",
             "text": "行2新", "translated text": ""},
        ])

        with open(xlsx_path, "rb") as fp:
            result_df, warnings = _internalUpdateDataFrame(new_df, fp)

        records = result_df.to_dict(orient="records")
        # First row: text unchanged, translation preserved
        assert records[0]["translated text"] == "줄1"
        assert records[0]["comments"] == ""
        # Second row: text changed, translation preserved with comment
        assert records[1]["translated text"] == "줄2"
        assert "원본 문자열이 수정되었습니다" in records[1]["comments"]


# ============================================================
# _internalDataFrameToXlsx
# ============================================================


class TestDataFrameToXlsxEdgeCases:
    def test_multiple_rows_with_formatting(self, tmp_path):
        df = pd.DataFrame([
            {"id": "0", "name": "A", "translated name": "",
             "text": "テスト1", "translated text": "테스트1"},
            {"id": "0", "name": "B", "translated name": "",
             "text": "テスト2", "translated text": "테스트2"},
        ])

        xlsx_path = str(tmp_path / "output.xlsx")
        with open(xlsx_path, "wb") as fp:
            _internalDataFrameToXlsx(df, fp)

        result = pd.read_excel(xlsx_path, engine="openpyxl")
        assert len(result) == 2


# ============================================================
# _internalCsvToTxt edge cases
# ============================================================


class TestCsvToTxtEdgeCases:
    def test_csv_fewer_rows_than_txt_raises(self, tmp_path):
        """When CSV has fewer rows than TXT messages, ValueError should be raised."""
        txt_path = str(tmp_path / "test.txt")
        create_adv_txt(txt_path, [
            {"tag": "message", "text": "一番目", "name": "A"},
            {"tag": "message", "text": "二番目", "name": "B"},
        ])

        with open(txt_path, "r", encoding="utf-8") as fp:
            txt_content = fp.read()

        # CSV with only 1 data row (matching first message only)
        xlsx_path = str(tmp_path / "test.xlsx")
        create_adv_xlsx(xlsx_path, [
            {"id": "0000000000000", "name": "A", "translated name": "",
             "text": "一番目", "translated text": "첫번째"},
        ])

        from scripts.adv import XlsxToCsv
        with open(xlsx_path, "rb") as fp:
            csv_io = StringIO()
            XlsxToCsv(fp, csv_io, "test.txt")
        csv_io.seek(0)
        csv_content = csv_io.read()

        with pytest.raises(ValueError, match="fewer rows"):
            _internalCsvToTxt(csv_content, txt_content)


class TestTxtToScvEdgeCases:
    def test_message_without_text_skipped(self, tmp_path):
        """Messages without text field should not produce CSV rows."""
        txt_path = str(tmp_path / "test.txt")
        # Write a txt with a message tag that has no text
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("[message name=A]\n[message text=テスト name=B]\n")

        with open(txt_path, "r", encoding="utf-8") as fp:
            result = _internalTxtToScv(fp, "test.txt")

        result.seek(0)
        content = result.read()
        assert "テスト" in content
