"""Unit tests for matcher — scoring, filtering, calibration."""

import pytest
from src.matcher import (
    score_job, score_title_match, score_location_match, score_level_match,
    score_keyword_boost, score_company_preference, score_recency,
    classify_priority, should_exclude,
)


class TestCalibration:
    """Auto-generated calibration: synthetic jobs from profile must score correctly."""

    def test_p1_job_scores_above_85(self, profile, p1_job):
        score = score_job(p1_job, profile)
        assert score >= 85, f"P1 job scored {score}, expected ≥85"

    def test_p1_alt_scores_above_85(self, profile, p1_job_alt):
        score = score_job(p1_job_alt, profile)
        assert score >= 85, f"P1 alt job scored {score}, expected ≥85"

    def test_p4_job_scores_below_50(self, profile, p4_job):
        score = score_job(p4_job, profile)
        assert score < 50, f"P4 job scored {score}, expected <50"

    def test_remote_bi_analyst_is_p1_or_p2(self, profile, remote_job):
        score = score_job(remote_job, profile)
        assert score >= 70, f"Remote analytics job scored {score}, expected ≥70"


class TestTitleMatch:
    def test_exact_match(self, profile):
        assert score_title_match("Data Analyst", profile) > 0.8

    def test_partial_match(self, profile):
        score = score_title_match("Sr. BI Engineer", profile)
        assert 0.3 < score < 1.0

    def test_no_match(self, profile):
        score = score_title_match("iOS Developer", profile)
        assert score < 0.4  # "developer" overlaps with "BI Developer" → ~0.33

    def test_empty_title(self, profile):
        assert score_title_match("", profile) == 0.0

    def test_case_insensitive(self, profile):
        s1 = score_title_match("DATA ANALYST", profile)
        s2 = score_title_match("data analyst", profile)
        assert s1 == s2


class TestLocationMatch:
    def test_exact_city(self, profile):
        assert score_location_match("Chandler, AZ", profile) == 1.0

    def test_phoenix_metro(self, profile):
        assert score_location_match("Tempe, AZ", profile) == 0.95

    def test_same_state(self, profile):
        assert score_location_match("Tucson, AZ", profile) == 0.8

    def test_remote(self, profile):
        assert score_location_match("Remote", profile) == 1.0

    def test_remote_partial(self, profile):
        assert score_location_match("Remote — US", profile) == 1.0

    def test_relocation_city(self, profile):
        assert score_location_match("San Francisco, CA", profile) == 0.7

    def test_other_us(self, profile):
        score = score_location_match("Chicago, IL", profile)
        assert 0.2 <= score <= 0.4

    def test_missing(self, profile):
        assert score_location_match("", profile) == 0.2

    def test_international(self, profile):
        assert score_location_match("London, UK", profile) == 0.2


class TestLevelMatch:
    def test_exact(self, profile):
        assert score_level_match("mid", profile) == 1.0

    def test_one_off(self, profile):
        assert score_level_match("senior", profile) == 0.7

    def test_two_off(self, profile):
        assert score_level_match("lead", profile) == 0.3

    def test_missing(self, profile):
        assert score_level_match("", profile) == 0.5


class TestKeywordBoost:
    def test_two_keywords(self, profile):
        score = score_keyword_boost("Business Intelligence Analytics", profile)
        assert score >= 0.5  # "intelligence" + "analytics"

    def test_no_keywords(self, profile):
        assert score_keyword_boost("iOS Developer", profile) == 0.0

    def test_capped_at_one(self, profile):
        score = score_keyword_boost("analytics intelligence reporting data insights dashboard", profile)
        assert score == 1.0


class TestCompanyPreference:
    def test_preferred(self, profile):
        job = {"company_slug": "anthropic"}
        assert score_company_preference(job, profile) == 1.0

    def test_not_preferred(self, profile):
        job = {"company_slug": "randomcorp"}
        assert score_company_preference(job, profile) == 0.0

    def test_workday_slug(self, profile):
        job = {"company_slug": "nvidia|wd5|NVIDIAExternalCareerSite"}
        assert score_company_preference(job, profile) == 1.0


class TestRecency:
    def test_today(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        assert score_recency(now) > 0.9

    def test_old(self):
        assert score_recency("2025-01-01T00:00:00Z") == 0.0

    def test_missing(self):
        assert score_recency("") == 0.5


class TestClassifyPriority:
    def test_p1(self):
        assert classify_priority(90) == "P1"

    def test_p2(self):
        assert classify_priority(75) == "P2"

    def test_p3(self):
        assert classify_priority(55) == "P3"

    def test_p4(self):
        assert classify_priority(30) == "P4"


class TestPreFilters:
    def test_exclude_intern(self, profile, intern_job):
        assert should_exclude(intern_job, profile) is True

    def test_exclude_recruiter(self, profile, recruiter_job):
        assert should_exclude(recruiter_job, profile) is True

    def test_exclude_intern_by_title(self, profile):
        job = {"title": "Summer Data Analytics Intern", "skill_level": "mid", "is_recruiter": False}
        assert should_exclude(job, profile) is True

    def test_keep_good_job(self, profile, p1_job):
        assert should_exclude(p1_job, profile) is False


class TestMissingFields:
    def test_minimal_job_doesnt_crash(self, profile, missing_fields_job):
        score = score_job(missing_fields_job, profile)
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_none_fields(self, profile):
        job = {"title": None, "location": None, "skill_level": None, "scraped_at": None}
        score = score_job(job, profile)
        assert isinstance(score, float)
