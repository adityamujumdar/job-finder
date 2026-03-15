"""Unit tests for downloader — cache behavior, validation gate."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.downloader import download_jba_data, _fallback_cache
from src.config import JBA_DIR, MIN_JBA_JOBS


class TestCacheBehavior:
    def test_cache_hit_skips_download(self, tmp_path):
        """If today's cache exists, don't download."""
        cache_file = tmp_path / "2026-03-15.json"
        cache_file.write_text(json.dumps([{"title": "test"}] * 200_000))

        with patch("src.downloader.JBA_DIR", tmp_path), \
             patch("src.downloader.today", return_value="2026-03-15"), \
             patch("src.downloader._download_manifest") as mock_dl:

            jobs = download_jba_data(force=False)
            mock_dl.assert_not_called()
            assert len(jobs) == 200_000

    def test_force_bypasses_cache(self, tmp_path):
        """force=True should download even if cache exists."""
        cache_file = tmp_path / "2026-03-15.json"
        cache_file.write_text(json.dumps([{"title": "old"}] * 200_000))

        manifest = {"chunks": ["chunk_0.json.gz"], "totalJobs": 200_000}
        fresh_jobs = [{"title": f"job_{i}"} for i in range(200_000)]

        with patch("src.downloader.JBA_DIR", tmp_path), \
             patch("src.downloader.today", return_value="2026-03-15"), \
             patch("src.downloader._download_manifest", return_value=manifest), \
             patch("src.downloader._download_chunk", return_value=fresh_jobs):

            jobs = download_jba_data(force=True)
            assert len(jobs) == 200_000
            assert jobs[0]["title"] == "job_0"


class TestValidationGate:
    def test_below_minimum_falls_back(self, tmp_path):
        """If download yields <100K jobs, fall back to cache."""
        # Create yesterday's cache
        yesterday = tmp_path / "2026-03-14.json"
        yesterday.write_text(json.dumps([{"title": "cached"}] * 150_000))

        manifest = {"chunks": ["chunk_0.json.gz"], "totalJobs": 500_000}

        with patch("src.downloader.JBA_DIR", tmp_path), \
             patch("src.downloader.today", return_value="2026-03-15"), \
             patch("src.downloader._download_manifest", return_value=manifest), \
             patch("src.downloader._download_chunk", return_value=[{"title": "x"}] * 50):

            jobs = download_jba_data(force=True)
            # Should fall back to yesterday's 150K
            assert len(jobs) == 150_000


class TestPartialFailure:
    def test_bad_chunks_skipped(self, tmp_path):
        """Corrupt chunks are skipped, good chunks are kept."""
        manifest = {"chunks": ["good.json.gz", "bad.json.gz"], "totalJobs": 200_000}
        good_jobs = [{"title": f"job_{i}"} for i in range(150_000)]

        def mock_chunk(name):
            if name == "good.json.gz":
                return good_jobs
            return []  # Bad chunk returns empty

        with patch("src.downloader.JBA_DIR", tmp_path), \
             patch("src.downloader.today", return_value="2026-03-15"), \
             patch("src.downloader._download_manifest", return_value=manifest), \
             patch("src.downloader._download_chunk", side_effect=mock_chunk):

            jobs = download_jba_data(force=True)
            assert len(jobs) == 150_000


class TestFallbackCache:
    def test_finds_most_recent(self, tmp_path):
        (tmp_path / "2026-03-13.json").write_text(json.dumps([1, 2, 3]))
        (tmp_path / "2026-03-14.json").write_text(json.dumps([1, 2, 3, 4]))

        with patch("src.downloader.JBA_DIR", tmp_path):
            result = _fallback_cache(tmp_path / "2026-03-15.json")
            assert len(result) == 4  # Most recent

    def test_no_cache_returns_empty(self, tmp_path):
        with patch("src.downloader.JBA_DIR", tmp_path):
            result = _fallback_cache(tmp_path / "2026-03-15.json")
            assert result == []
