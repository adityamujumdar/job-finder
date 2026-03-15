"""Unit tests for report generator."""

import csv
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.report import generate_report, _write_csv, _build_summary, CSV_COLUMNS


class TestCSVGeneration:
    def test_csv_has_correct_columns(self, tmp_path):
        scored = [
            {
                "_priority": "P1", "_score": 92.5,
                "title": "BI Analyst", "company": "Anthropic",
                "location": "Remote", "url": "https://example.com/1",
                "ats": "Greenhouse", "skill_level": "mid",
                "scraped_at": "2026-03-15T00:00:00Z",
            },
            {
                "_priority": "P3", "_score": 55.0,
                "title": "SWE", "company": "Acme",
                "location": "NYC", "url": "https://example.com/2",
                "ats": "Lever", "skill_level": "senior",
                "scraped_at": "2026-03-14T00:00:00Z",
            },
        ]
        csv_path = tmp_path / "test.csv"
        _write_csv(csv_path, scored)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames) == set(CSV_COLUMNS)
            rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["priority"] == "P1"
            assert rows[0]["company"] == "Anthropic"

    def test_empty_csv(self, tmp_path):
        csv_path = tmp_path / "empty.csv"
        _write_csv(csv_path, [])
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert list(reader) == []


class TestSummary:
    def test_summary_contains_key_info(self):
        scored = [
            {"_priority": "P1", "_score": 95, "title": "BI Analyst", "company": "Stripe",
             "location": "Remote", "url": "https://x.com", "ats": "Greenhouse"},
            {"_priority": "P2", "_score": 75, "title": "Data Eng", "company": "Acme",
             "location": "NYC", "url": "https://y.com", "ats": "Lever"},
        ]
        summary = _build_summary(scored, "2026-03-15", top_n=10)
        assert "2026-03-15" in summary
        assert "P1" in summary
        assert "BI Analyst" in summary
        assert "Stripe" in summary

    def test_no_p1_shows_p2(self):
        scored = [
            {"_priority": "P2", "_score": 75, "title": "Analyst", "company": "X",
             "location": "Remote", "url": "https://x.com", "ats": "GH"},
        ]
        summary = _build_summary(scored, "2026-03-15", top_n=5)
        assert "P2" in summary
        assert "Analyst" in summary
