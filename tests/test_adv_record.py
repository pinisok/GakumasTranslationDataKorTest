"""Tests for adv_record module — record/DataFrame processing."""

import csv
from io import StringIO

import pandas as pd
import pytest

from scripts.adv_record import (
    _internalOverrideXlsxColumn,
    _internalXlsxDataFrameProcess,
    _internalXlsxRecordsProcess,
    _internalCsvWriter,
)


class TestXlsxDataFrameProcess:
    def test_appends_info_and_translator_rows(self):
        df = pd.DataFrame([
            {"id": "0", "name": "A", "translated name": "", "text": "t", "translated text": "tr"},
        ])
        _internalXlsxDataFrameProcess(df, "test.txt")
        records = df.to_dict(orient="records")
        assert len(records) == 3
        assert records[1]["id"] == "info"
        assert records[1]["name"] == "test.txt"
        assert records[2]["id"] == "译者"

    def test_drops_extra_columns(self):
        df = pd.DataFrame([
            {"c0": "0", "c1": "A", "c2": "", "c3": "t", "c4": "tr", "c5": "extra", "c6": "extra2"},
        ])
        _internalOverrideXlsxColumn(df)
        _internalXlsxDataFrameProcess(df, "test.txt")
        # Extra columns beyond 5 should be dropped
        assert len(df.columns) == 5


class TestXlsxRecordsProcessEdgeCases:
    def test_non_str_non_int_id_becomes_empty(self):
        records = [
            {"id": 3.14, "name": "t", "translated name": "",
             "text": "hello", "translated text": "안녕"}
        ]
        result = _internalXlsxRecordsProcess(records)
        assert result[0]["id"] == ""

    def test_non_str_name_becomes_empty(self):
        records = [
            {"id": "1", "name": 123, "translated name": "",
             "text": "hello", "translated text": "안녕"}
        ]
        result = _internalXlsxRecordsProcess(records)
        assert result[0]["name"] == ""

    def test_whitespace_only_translated_name_ignored(self):
        records = [
            {"id": "1", "name": "麻央", "translated name": "   ",
             "text": "hello", "translated text": "안녕"}
        ]
        result = _internalXlsxRecordsProcess(records)
        assert result[0]["name"] == "마오"  # Falls through to CHARACTER_REGEX_TRANS_MAP

    def test_non_str_text_becomes_empty(self):
        records = [
            {"id": "info", "name": "f.txt", "translated name": "",
             "text": 42, "translated text": ""}
        ]
        result = _internalXlsxRecordsProcess(records)
        assert result[0]["text"] == ""

    def test_int_translated_text_becomes_string(self):
        records = [
            {"id": "1", "name": "t", "translated name": "",
             "text": "hello", "translated text": 42}
        ]
        result = _internalXlsxRecordsProcess(records)
        assert result[0]["translated text"] == "42"


class TestCsvWriter:
    def test_writes_header_and_rows(self):
        fp = StringIO()
        records = [
            {"id": "1", "name": "마오", "text": "hello", "translated text": "안녕"},
            {"id": "info", "name": "test.txt", "text": "", "translated text": ""},
        ]
        _internalCsvWriter(fp, records)
        fp.seek(0)
        lines = fp.readlines()
        assert len(lines) == 3  # header + 2 rows
        assert "id,name,text,trans\n" == lines[0]

    def test_csv_is_parseable(self):
        fp = StringIO()
        records = [
            {"id": "1", "name": "A", "text": "hello,world", "translated text": "안녕,세계"},
        ]
        _internalCsvWriter(fp, records)
        fp.seek(0)
        reader = csv.DictReader(fp)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["text"] == "hello,world"
        assert rows[0]["trans"] == "안녕,세계"
