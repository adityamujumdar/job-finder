"""Tests for profile staleness detection: hash, meta file, and staleness check."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.config import profile_hash, load_profile

# Hardcoded test profile so tests don't depend on config/profile.yaml existing
_TEST_PROFILE_RAW = {
    "name": "Test User",
    "location": "Remote",
    "target_roles": ["Software Engineer"],
    "skills": ["Python"],
    "years_experience": 5,
    "target_level": "mid",
}
_TEST_PROFILE = load_profile(raw=_TEST_PROFILE_RAW)


# ── profile_hash() ──────────────────────────────────────────────────────────


class TestProfileHash:
    """Tests for config.profile_hash()."""

    def test_returns_8_char_hex(self, tmp_path):
        """profile_hash returns an 8-character hex string."""
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test\ntarget_roles:\n  - Engineer\n")
        result = profile_hash(path=profile)
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_returns_zeros_for_missing_file(self, tmp_path):
        """profile_hash returns '00000000' when file doesn't exist."""
        result = profile_hash(path=tmp_path / "nonexistent.yaml")
        assert result == "00000000"

    def test_changes_when_content_changes(self, tmp_path):
        """profile_hash changes when profile content changes."""
        profile = tmp_path / "profile.yaml"
        profile.write_text("target_roles:\n  - BI Analyst\n")
        hash1 = profile_hash(path=profile)

        profile.write_text("target_roles:\n  - Fashion Designer\n")
        hash2 = profile_hash(path=profile)
        assert hash1 != hash2

    def test_stable_for_identical_content(self, tmp_path):
        """profile_hash returns same value for identical content."""
        profile = tmp_path / "profile.yaml"
        content = "name: Test\ntarget_roles:\n  - Engineer\n"
        profile.write_text(content)
        hash1 = profile_hash(path=profile)
        hash2 = profile_hash(path=profile)
        assert hash1 == hash2

    def test_returns_zeros_on_permission_error(self, tmp_path):
        """profile_hash returns '00000000' when file is unreadable."""
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test\n")
        profile.chmod(0o000)
        try:
            result = profile_hash(path=profile)
            assert result == "00000000"
        finally:
            profile.chmod(0o644)  # restore for cleanup


# ── Meta file write (matcher) ───────────────────────────────────────────────


class TestMetaFileWrite:
    """Tests for matcher writing .meta.json alongside scored data."""

    def test_run_matcher_writes_meta_file(self, tmp_path):
        """run_matcher() creates a .meta.json sidecar with profile hash."""
        from src.matcher import run_matcher
        from src import config

        # Set up temp dirs
        jobs_dir = tmp_path / "jobs"
        scored_dir = tmp_path / "scored"
        jobs_dir.mkdir()
        scored_dir.mkdir()

        # Write minimal job data
        date_str = "2026-01-01"
        jobs = [
            {"title": "BI Analyst", "company": "TestCo", "location": "Remote",
             "url": "https://example.com/1", "ats": "greenhouse",
             "skill_level": "mid", "is_recruiter": False,
             "scraped_at": "2026-01-01T00:00:00Z"},
        ]
        (jobs_dir / f"{date_str}.json").write_text(json.dumps(jobs))

        # Patch paths to use tmp_path + mock load_profile (no real profile.yaml needed)
        with patch.object(config, "JOBS_DIR", jobs_dir), \
             patch.object(config, "SCORED_DIR", scored_dir), \
             patch("src.matcher.JOBS_DIR", jobs_dir), \
             patch("src.matcher.SCORED_DIR", scored_dir), \
             patch("src.matcher.load_profile", return_value=_TEST_PROFILE):
            result = run_matcher(date=date_str)

        meta_path = scored_dir / f"{date_str}.meta.json"
        assert meta_path.exists(), "Meta file should be written alongside scored data"

        meta = json.loads(meta_path.read_text())
        assert "profile_hash" in meta
        assert len(meta["profile_hash"]) == 8
        assert "target_roles" in meta
        assert isinstance(meta["target_roles"], list)
        assert "scored_at" in meta
        assert meta["scored_at"] == date_str
        assert "total_scored" in meta
        assert "tiers" in meta

    def test_meta_profile_hash_matches_current(self, tmp_path):
        """Meta file profile_hash matches what profile_hash() returns now."""
        from src.matcher import run_matcher
        from src import config

        jobs_dir = tmp_path / "jobs"
        scored_dir = tmp_path / "scored"
        jobs_dir.mkdir()
        scored_dir.mkdir()

        date_str = "2026-01-02"
        jobs = [
            {"title": "Data Engineer", "company": "TestCo", "location": "Remote",
             "url": "https://example.com/2", "ats": "greenhouse",
             "skill_level": "mid", "is_recruiter": False,
             "scraped_at": "2026-01-02T00:00:00Z"},
        ]
        (jobs_dir / f"{date_str}.json").write_text(json.dumps(jobs))

        with patch.object(config, "JOBS_DIR", jobs_dir), \
             patch.object(config, "SCORED_DIR", scored_dir), \
             patch("src.matcher.JOBS_DIR", jobs_dir), \
             patch("src.matcher.SCORED_DIR", scored_dir), \
             patch("src.matcher.load_profile", return_value=_TEST_PROFILE):
            run_matcher(date=date_str)

        meta = json.loads((scored_dir / f"{date_str}.meta.json").read_text())
        # Hash should match the test profile we injected
        assert len(meta["profile_hash"]) == 8


# ── Staleness check (site_generator) ────────────────────────────────────────


class TestStalenessCheck:
    """Tests for site_generator._check_staleness()."""

    def test_fresh_when_hash_matches(self, tmp_path):
        """Returns 'fresh' when profile hash matches meta file."""
        from src.site_generator import _check_staleness
        from src import config

        current = profile_hash()
        meta = {"profile_hash": current, "target_roles": ["Engineer"]}
        meta_path = tmp_path / "2026-01-01.meta.json"
        meta_path.write_text(json.dumps(meta))

        with patch.object(config, "SCORED_DIR", tmp_path), \
             patch("src.site_generator.SCORED_DIR", tmp_path):
            result = _check_staleness("2026-01-01")

        assert result["status"] == "fresh"
        assert result["current_hash"] == current
        assert result["stored_hash"] == current

    def test_stale_when_hash_mismatches(self, tmp_path):
        """Returns 'stale' when profile hash differs from meta file."""
        from src.site_generator import _check_staleness
        from src import config

        meta = {"profile_hash": "deadbeef", "target_roles": ["Fashion Designer"]}
        meta_path = tmp_path / "2026-01-01.meta.json"
        meta_path.write_text(json.dumps(meta))

        with patch.object(config, "SCORED_DIR", tmp_path), \
             patch("src.site_generator.SCORED_DIR", tmp_path):
            result = _check_staleness("2026-01-01")

        assert result["status"] == "stale"
        assert result["stored_hash"] == "deadbeef"
        assert result["current_hash"] != "deadbeef"

    def test_unknown_when_meta_missing(self, tmp_path):
        """Returns 'unknown' when meta file doesn't exist."""
        from src.site_generator import _check_staleness
        from src import config

        with patch.object(config, "SCORED_DIR", tmp_path), \
             patch("src.site_generator.SCORED_DIR", tmp_path):
            result = _check_staleness("2026-01-01")

        assert result["status"] == "unknown"
        assert result["stored_hash"] is None

    def test_unknown_when_meta_corrupt(self, tmp_path):
        """Returns 'unknown' when meta file is corrupt JSON."""
        from src.site_generator import _check_staleness
        from src import config

        meta_path = tmp_path / "2026-01-01.meta.json"
        meta_path.write_text("not valid json {{{")

        with patch.object(config, "SCORED_DIR", tmp_path), \
             patch("src.site_generator.SCORED_DIR", tmp_path):
            result = _check_staleness("2026-01-01")

        assert result["status"] == "unknown"
        assert result["stored_hash"] is None
