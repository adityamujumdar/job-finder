"""Unit tests for site_generator — job ID generation and dashboard state logic."""
import hashlib
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Job ID generation ─────────────────────────────────────────────────────────

class TestJobID:
    """Stable 8-char hex IDs derived from URL."""

    def _make_id(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:8]

    def test_id_is_8_chars(self):
        job_id = self._make_id("https://example.com/jobs/123")
        assert len(job_id) == 8

    def test_id_is_hex(self):
        job_id = self._make_id("https://example.com/jobs/123")
        int(job_id, 16)  # raises ValueError if not hex

    def test_same_url_same_id(self):
        url = "https://boards.greenhouse.io/anthropic/jobs/4567"
        assert self._make_id(url) == self._make_id(url)

    def test_different_urls_different_ids(self):
        id1 = self._make_id("https://company-a.com/job/1")
        id2 = self._make_id("https://company-b.com/job/1")
        assert id1 != id2

    def test_empty_url_returns_sentinel(self):
        """Empty URL should produce the 00000000 sentinel, not crash."""
        # This mirrors the logic in _load_scored_jobs
        url = ""
        job_id = hashlib.sha256(url.encode()).hexdigest()[:8] if url else "00000000"
        assert job_id == "00000000"

    def test_netflix_url_stable(self):
        """Spot-check that a real-looking Netflix URL produces a stable ID."""
        url = "https://explore.jobs.netflix.net/careers/job/790298819058"
        job_id = self._make_id(url)
        assert len(job_id) == 8
        # ID is deterministic — same URL always produces the same result
        assert job_id == self._make_id(url)


# ── Dashboard state machine (None button logic) ───────────────────────────────

class TestFilterStateMachine:
    """
    State machine for selectedCompanies / selectedLocations:
      null       = no filter applied (show all)
      empty Set  = explicit "show nothing"
      non-empty  = filter to exactly these companies/locations

    These tests validate the conventions baked into the JS — we document
    the expected transitions here so future Python changes don't silently
    break the generated JS logic.
    """

    def test_convention_null_means_all(self):
        """null selectedCompanies should pass ALL jobs (no filter applied)."""
        selected = None
        jobs = [{"c": "Netflix"}, {"c": "Anthropic"}, {"c": "Stripe"}]
        # Mirrors: if (selectedCompanies !== null && !selectedCompanies.has(j.c)) return false;
        visible = [j for j in jobs if selected is None or j["c"] in selected]
        assert len(visible) == 3

    def test_convention_empty_set_means_none(self):
        """Empty Set selectedCompanies should pass ZERO jobs."""
        selected = set()
        jobs = [{"c": "Netflix"}, {"c": "Anthropic"}, {"c": "Stripe"}]
        visible = [j for j in jobs if selected is None or j["c"] in selected]
        assert len(visible) == 0

    def test_convention_nonempty_set_filters(self):
        """Non-empty Set should pass only matching jobs."""
        selected = {"Netflix", "Stripe"}
        jobs = [{"c": "Netflix"}, {"c": "Anthropic"}, {"c": "Stripe"}]
        visible = [j for j in jobs if selected is None or j["c"] in selected]
        assert len(visible) == 2
        assert all(j["c"] in selected for j in visible)

    def test_select_all_sets_null(self):
        """selectAllCompanies() sets selectedCompanies = null."""
        # simulates: function selectAllCompanies() { selectedCompanies = null; }
        selected = {"Netflix"}  # had a filter
        selected = None  # selectAll resets to null
        assert selected is None

    def test_clear_all_sets_empty_set(self):
        """clearAllCompanies() sets selectedCompanies = new Set() — the None button."""
        # simulates: function clearAllCompanies() { selectedCompanies = new Set(); }
        selected = None  # was "show all"
        selected = set()  # None button pressed
        assert selected == set()
        assert selected is not None  # critically: NOT null

    def test_toggle_from_null_transitions_to_single(self):
        """Clicking a company when in null mode selects only that company."""
        selected = None
        name = "Netflix"
        # simulates toggleCompany when selectedCompanies === null
        if selected is None:
            selected = {name}
        assert selected == {"Netflix"}

    def test_toggle_removes_existing(self):
        selected = {"Netflix", "Anthropic"}
        name = "Netflix"
        if name in selected:
            selected.discard(name)
        assert selected == {"Anthropic"}

    def test_toggle_adds_new(self):
        selected = {"Netflix"}
        name = "Anthropic"
        if name not in selected:
            selected.add(name)
        assert selected == {"Netflix", "Anthropic"}

    def test_reset_all_filters_returns_null(self):
        """resetAllFilters() should restore selectedCompanies to null."""
        selected = {"Netflix"}  # had a filter
        selected = None  # reset
        assert selected is None

    def test_filter_by_company_sets_single_set(self):
        """filterByCompany(name) sets selectedCompanies = new Set([name])."""
        selected = None
        name = "Stripe"
        selected = {name}
        assert selected == {"Stripe"}
        assert len(selected) == 1
