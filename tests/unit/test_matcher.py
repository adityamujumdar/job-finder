"""Unit tests for matcher — scoring, filtering, calibration.

Profile-agnostic: tests use hardcoded fixtures from conftest.py, not config/profile.yaml.
Two profile variants: bi_profile (BI/Data) and swe_profile (Backend SWE).
"""

import json
import pytest
from src.matcher import (
    score_job, score_title_match, score_location_match, score_level_match,
    score_keyword_boost, score_company_preference, score_recency,
    classify_priority, should_exclude, score_and_save_browsed,
)
from src.jba_fetcher import job_tier_classification


# ── Calibration Tests (BI Profile) ──────────────────────────────────────────

class TestCalibrationBI:
    """Synthetic jobs from BI profile must score correctly."""

    def test_p1_job_scores_above_85(self, bi_profile, p1_job):
        score = score_job(p1_job, bi_profile)
        assert score >= 85, f"P1 job scored {score}, expected ≥85"

    def test_p1_alt_scores_above_85(self, bi_profile, p1_job_alt):
        score = score_job(p1_job_alt, bi_profile)
        assert score >= 85, f"P1 alt job scored {score}, expected ≥85"

    def test_p4_job_scores_below_50(self, bi_profile, p4_job):
        score = score_job(p4_job, bi_profile)
        assert score < 50, f"P4 job scored {score}, expected <50"

    def test_remote_bi_analyst_is_p1_or_p2(self, bi_profile, remote_job):
        score = score_job(remote_job, bi_profile)
        assert score >= 70, f"Remote analytics job scored {score}, expected ≥70"


# ── Calibration Tests (SWE Profile) ─────────────────────────────────────────

class TestCalibrationSWE:
    """Synthetic jobs from SWE profile must score correctly."""

    def test_swe_p1_job_scores_above_85(self, swe_profile, swe_p1_job):
        score = score_job(swe_p1_job, swe_profile)
        assert score >= 85, f"SWE P1 job scored {score}, expected ≥85"

    def test_p4_job_scores_below_50(self, swe_profile, p4_job):
        score = score_job(p4_job, swe_profile)
        assert score < 50, f"P4 job scored {score}, expected <50"


# ── Title Match Tests ────────────────────────────────────────────────────────

class TestTitleMatchBI:
    def test_exact_match(self, bi_profile):
        assert score_title_match("Data Analyst", bi_profile) > 0.8

    def test_partial_match(self, bi_profile):
        score = score_title_match("Sr. BI Engineer", bi_profile)
        assert 0.3 < score < 1.0

    def test_no_match(self, bi_profile):
        score = score_title_match("iOS Developer", bi_profile)
        assert score < 0.4

    def test_empty_title(self, bi_profile):
        assert score_title_match("", bi_profile) == 0.0

    def test_case_insensitive(self, bi_profile):
        s1 = score_title_match("DATA ANALYST", bi_profile)
        s2 = score_title_match("data analyst", bi_profile)
        assert s1 == s2

    def test_swe_title_penalized_for_bi(self, bi_profile):
        """SWE titles should be heavily penalized for a BI profile."""
        score = score_title_match("Software Engineer - Data Analytics", bi_profile)
        assert score <= 0.35, f"SWE title scored {score} for BI profile, expected ≤0.35"


class TestTitleMatchSWE:
    def test_backend_engineer(self, swe_profile):
        assert score_title_match("Backend Engineer", swe_profile) > 0.8

    def test_senior_software_engineer(self, swe_profile):
        assert score_title_match("Senior Software Engineer", swe_profile) > 0.8

    def test_swe_profile_no_swe_penalty(self, swe_profile):
        """SWE titles should NOT be penalized for an SWE profile."""
        score = score_title_match("Software Engineer", swe_profile)
        assert score > 0.8, f"SWE title scored {score} for SWE profile, expected >0.8"

    def test_backend_with_suffix(self, swe_profile):
        """'Backend Engineer, Core Tech, Canada' should score well."""
        score = score_title_match("Backend Engineer, Core Tech, Canada", swe_profile)
        assert score > 0.8, f"Backend + suffix scored {score}, expected >0.8"

    def test_exclude_pattern_caps_score(self, swe_profile):
        """Titles matching exclude_title_patterns should be capped at 0.15."""
        score = score_title_match("Cloud Platform Engineer", swe_profile)
        assert score == 0.15, f"Excluded title scored {score}, expected 0.15"

    def test_exclude_pattern_devops(self, swe_profile):
        score = score_title_match("Senior DevOps Engineer", swe_profile)
        assert score == 0.15

    def test_exclude_pattern_no_match(self, swe_profile):
        """Normal titles should not be affected by exclude patterns."""
        score = score_title_match("Backend Engineer", swe_profile)
        assert score > 0.8

    def test_data_analyst_low_for_swe(self, swe_profile):
        """BI titles should score low for SWE profile."""
        score = score_title_match("Data Analyst", swe_profile)
        assert score < 0.3


# ── Location Match Tests ─────────────────────────────────────────────────────

class TestLocationMatchBI:
    def test_exact_city(self, bi_profile):
        assert score_location_match("Chandler, AZ", bi_profile) == 1.0

    def test_metro(self, bi_profile):
        assert score_location_match("Tempe, AZ", bi_profile) == 0.95

    def test_same_state(self, bi_profile):
        assert score_location_match("Tucson, AZ", bi_profile) == 0.8

    def test_remote(self, bi_profile):
        assert score_location_match("Remote", bi_profile) == 1.0

    def test_remote_partial(self, bi_profile):
        assert score_location_match("Remote — US", bi_profile) == 1.0

    def test_relocation_city(self, bi_profile):
        assert score_location_match("San Francisco, CA", bi_profile) == 0.7

    def test_other_us(self, bi_profile):
        score = score_location_match("Chicago, IL", bi_profile)
        assert 0.2 <= score <= 0.4

    def test_missing(self, bi_profile):
        assert score_location_match("", bi_profile) == 0.2

    def test_international(self, bi_profile):
        assert score_location_match("London, UK", bi_profile) == 0.2


class TestLocationMatchSWE:
    def test_exact_city(self, swe_profile):
        assert score_location_match("Toronto, Canada", swe_profile) == 1.0

    def test_metro(self, swe_profile):
        assert score_location_match("Mississauga, ON", swe_profile) == 0.95

    def test_relocation_city(self, swe_profile):
        assert score_location_match("Vancouver, BC", swe_profile) == 0.7

    def test_remote(self, swe_profile):
        assert score_location_match("Remote", swe_profile) == 1.0

    def test_empty_metro_no_false_match(self, swe_profile):
        """A city NOT in metro_cities should not get 0.95 even if it's a real metro."""
        # Phoenix is not in the SWE profile's metro_cities (which has GTA cities)
        score = score_location_match("Phoenix, AZ", swe_profile)
        assert score < 0.95, "Phoenix should not match Toronto metro"


# ── Level Match Tests ────────────────────────────────────────────────────────

class TestLevelMatchBI:
    """BI profile targets 'mid' level."""

    def test_exact(self, bi_profile):
        assert score_level_match("mid", bi_profile) == 1.0

    def test_one_off(self, bi_profile):
        assert score_level_match("senior", bi_profile) == 0.7

    def test_two_off(self, bi_profile):
        assert score_level_match("lead", bi_profile) == 0.3

    def test_missing(self, bi_profile):
        assert score_level_match("", bi_profile) == 0.5


class TestLevelMatchSWE:
    """SWE profile targets 'senior' level."""

    def test_exact(self, swe_profile):
        assert score_level_match("senior", swe_profile) == 1.0

    def test_one_off_down(self, swe_profile):
        assert score_level_match("mid", swe_profile) == 0.7

    def test_one_off_up(self, swe_profile):
        assert score_level_match("lead", swe_profile) == 0.7


# ── Keyword Boost Tests ──────────────────────────────────────────────────────

class TestKeywordBoostBI:
    def test_two_keywords(self, bi_profile):
        score = score_keyword_boost("Business Intelligence Analytics", bi_profile)
        assert score >= 0.5  # "intelligence" + "analytics"

    def test_no_keywords(self, bi_profile):
        assert score_keyword_boost("iOS Developer", bi_profile) == 0.0

    def test_capped_at_one(self, bi_profile):
        score = score_keyword_boost(
            "analytics intelligence reporting data insights dashboard", bi_profile
        )
        assert score == 1.0


class TestKeywordBoostSWE:
    def test_backend_keywords(self, swe_profile):
        score = score_keyword_boost("Backend Distributed API", swe_profile)
        assert score >= 0.5

    def test_no_keywords(self, swe_profile):
        assert score_keyword_boost("Nurse Practitioner", swe_profile) == 0.0


# ── Company Preference Tests ─────────────────────────────────────────────────

class TestCompanyPreference:
    def test_preferred(self, bi_profile):
        job = {"company_slug": "anthropic"}
        assert score_company_preference(job, bi_profile) == 1.0

    def test_not_preferred(self, bi_profile):
        job = {"company_slug": "randomcorp"}
        assert score_company_preference(job, bi_profile) == 0.0

    def test_workday_slug(self, bi_profile):
        job = {"company_slug": "nvidia|wd5|NVIDIAExternalCareerSite"}
        assert score_company_preference(job, bi_profile) == 1.0


# ── Recency Tests ────────────────────────────────────────────────────────────

class TestRecency:
    def test_today(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        assert score_recency(now) > 0.9

    def test_old(self):
        assert score_recency("2025-01-01T00:00:00Z") == 0.0

    def test_missing(self):
        assert score_recency("") == 0.5

    def test_recency_weight_zero(self, bi_profile):
        """With recency weight = 0.00, recent vs old jobs should score the same."""
        from datetime import datetime, timezone, timedelta
        recent = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        job_recent = {
            "title": "Data Analyst", "location": "Remote",
            "skill_level": "mid", "scraped_at": recent,
        }
        job_old = dict(job_recent, scraped_at=old)
        # Scores should be identical since recency weight is 0
        assert score_job(job_recent, bi_profile) == score_job(job_old, bi_profile)


# ── Classify Priority Tests ──────────────────────────────────────────────────

class TestClassifyPriority:
    def test_p1(self):
        assert classify_priority(90) == "P1"

    def test_p2(self):
        assert classify_priority(75) == "P2"

    def test_p3(self):
        assert classify_priority(55) == "P3"

    def test_p4(self):
        assert classify_priority(30) == "P4"


# ── Pre-Filter Tests ─────────────────────────────────────────────────────────

class TestPreFilters:
    def test_exclude_intern(self, bi_profile, intern_job):
        assert should_exclude(intern_job, bi_profile) is True

    def test_exclude_recruiter(self, bi_profile, recruiter_job):
        assert should_exclude(recruiter_job, bi_profile) is True

    def test_exclude_intern_by_title(self, bi_profile):
        job = {"title": "Summer Data Analytics Intern", "skill_level": "mid", "is_recruiter": False}
        assert should_exclude(job, bi_profile) is True

    def test_keep_good_job(self, bi_profile, p1_job):
        assert should_exclude(p1_job, bi_profile) is False


# ── Missing Fields Tests ─────────────────────────────────────────────────────

class TestMissingFields:
    def test_minimal_job_doesnt_crash(self, bi_profile, missing_fields_job):
        score = score_job(missing_fields_job, bi_profile)
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_none_fields(self, bi_profile):
        job = {"title": None, "location": None, "skill_level": None, "scraped_at": None}
        score = score_job(job, bi_profile)
        assert isinstance(score, float)


# ── Level Detection Tests (jba_fetcher) ──────────────────────────────────────

class TestLevelDetection:
    def test_core_tech_is_mid(self):
        """'Core Tech' should NOT trigger the 'tech' penalty → mid, not entry."""
        assert job_tier_classification("Backend Engineer, Core Tech, Canada") == "mid"

    def test_core_tech_no_suffix(self):
        assert job_tier_classification("Backend Engineer, Core Tech") == "mid"

    def test_plain_backend_is_mid(self):
        assert job_tier_classification("Backend Engineer") == "mid"

    def test_senior_is_senior(self):
        assert job_tier_classification("Senior Backend Engineer") == "senior"

    def test_intern_is_intern(self):
        assert job_tier_classification("Software Engineering Intern") == "intern"

    def test_staff_is_senior(self):
        assert job_tier_classification("Staff Software Engineer") == "senior"


# ── Preferred Company Weight Tests ───────────────────────────────────────────

class TestPreferredCompanyWeight:
    def test_preferred_gives_bonus(self, bi_profile):
        """Preferred company job should score higher than identical non-preferred job."""
        from datetime import datetime
        base = {
            "title": "Data Analyst", "location": "Remote",
            "skill_level": "mid", "is_recruiter": False,
            "scraped_at": datetime.now().isoformat(),
        }
        preferred = dict(base, company_slug="anthropic")
        non_preferred = dict(base, company_slug="randomcorp")
        diff = score_job(preferred, bi_profile) - score_job(non_preferred, bi_profile)
        # company_preference weight is 0.15 → max 15 point bonus
        assert 10 <= diff <= 15, f"Preferred company bonus was {diff}, expected 10-15"


# ── Browsed Job Integration Tests ────────────────────────────────────────────

class TestScoreAndSaveBrowsed:
    """Tests for score_and_save_browsed() — browsed jobs get scored and persisted."""

    def test_basic_score_and_save(self, bi_profile, tmp_path, monkeypatch):
        """Happy path: browsed job gets scored, saved, tagged _source=browse."""
        monkeypatch.setattr("src.matcher.load_profile", lambda: bi_profile)
        monkeypatch.setattr("src.matcher.SCORED_DIR", tmp_path)

        job = {
            "title": "Data Analyst",
            "company": "Scotiabank",
            "url": "https://scotiabank.com/jobs/12345",
            "location": "Toronto, ON",
        }
        result = score_and_save_browsed(job, date="2026-03-18")

        assert result["_score"] > 0
        assert result["_priority"] in ("P1", "P2", "P3", "P4")
        assert result["_source"] == "browse"
        assert result["ats"] == "browse"

        # Verify it was persisted
        saved = json.loads((tmp_path / "2026-03-18.json").read_text())
        assert len(saved) == 1
        assert saved[0]["url"] == "https://scotiabank.com/jobs/12345"

    def test_missing_required_fields(self, bi_profile, monkeypatch):
        """Rejects jobs missing title, company, or url."""
        monkeypatch.setattr("src.matcher.load_profile", lambda: bi_profile)

        with pytest.raises(ValueError, match="missing required fields"):
            score_and_save_browsed({"title": "Data Analyst"})

        with pytest.raises(ValueError, match="missing required fields"):
            score_and_save_browsed({"title": "Analyst", "company": "X"})

    def test_dedup_by_url(self, bi_profile, tmp_path, monkeypatch):
        """Re-browsing same URL replaces the old entry, not duplicates."""
        monkeypatch.setattr("src.matcher.load_profile", lambda: bi_profile)
        monkeypatch.setattr("src.matcher.SCORED_DIR", tmp_path)

        job = {
            "title": "Data Analyst",
            "company": "Scotiabank",
            "url": "https://scotiabank.com/jobs/12345",
        }
        score_and_save_browsed(job, date="2026-03-18")
        score_and_save_browsed(job, date="2026-03-18")  # same URL again

        saved = json.loads((tmp_path / "2026-03-18.json").read_text())
        assert len(saved) == 1, "Should not duplicate — dedup by URL"

    def test_no_existing_file(self, bi_profile, tmp_path, monkeypatch):
        """Works when no scored file exists yet (creates it)."""
        monkeypatch.setattr("src.matcher.load_profile", lambda: bi_profile)
        monkeypatch.setattr("src.matcher.SCORED_DIR", tmp_path)

        job = {
            "title": "BI Developer",
            "company": "NewCo",
            "url": "https://newco.com/jobs/1",
        }
        result = score_and_save_browsed(job, date="2026-03-19")

        assert result["_score"] > 0
        assert (tmp_path / "2026-03-19.json").exists()

    def test_appends_to_existing(self, bi_profile, tmp_path, monkeypatch):
        """Browsed job appends to existing scored data, doesn't overwrite."""
        monkeypatch.setattr("src.matcher.load_profile", lambda: bi_profile)
        monkeypatch.setattr("src.matcher.SCORED_DIR", tmp_path)

        # Seed with an existing job
        existing = [{"title": "Existing Job", "company": "X", "url": "https://x.com/1",
                      "_score": 90.0, "_priority": "P1"}]
        (tmp_path / "2026-03-18.json").write_text(json.dumps(existing))

        job = {
            "title": "Data Analyst",
            "company": "Scotiabank",
            "url": "https://scotiabank.com/jobs/12345",
        }
        score_and_save_browsed(job, date="2026-03-18")

        saved = json.loads((tmp_path / "2026-03-18.json").read_text())
        assert len(saved) == 2, "Should append, not overwrite"
        urls = {j["url"] for j in saved}
        assert "https://x.com/1" in urls
        assert "https://scotiabank.com/jobs/12345" in urls
