"""Shared test fixtures — including auto-generated calibration jobs from profile."""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_profile, today


@pytest.fixture
def profile():
    """Load the real profile for testing."""
    return load_profile()


@pytest.fixture
def p1_job():
    """A synthetic job that MUST score P1 (≥85) — perfect match for Aditya's profile."""
    return {
        "title": "Business Intelligence Analyst",
        "company": "Anthropic",
        "location": "Remote",
        "url": "https://boards.greenhouse.io/anthropic/jobs/12345",
        "ats": "greenhouse",
        "slug": "anthropic",
        "skill_level": "mid",
        "is_recruiter": False,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def p1_job_alt():
    """Another P1 — Data Analyst in Chandler, AZ at a preferred company."""
    return {
        "title": "Data Analyst - Analytics & Reporting",
        "company": "Stripe",
        "location": "Chandler, AZ",
        "url": "https://boards.greenhouse.io/stripe/jobs/67890",
        "ats": "greenhouse",
        "slug": "stripe",
        "skill_level": "mid",
        "is_recruiter": False,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def p4_job():
    """A synthetic job that MUST score P4 (<50) — terrible match."""
    return {
        "title": "Senior iOS Engineer",
        "company": "RandomStartup",
        "location": "Tokyo, Japan",
        "url": "https://boards.greenhouse.io/randomstartup/jobs/99999",
        "ats": "greenhouse",
        "slug": "randomstartup",
        "skill_level": "senior",
        "is_recruiter": False,
        "scraped_at": (datetime.now() - timedelta(days=25)).isoformat(),
    }


@pytest.fixture
def intern_job():
    """Should be filtered out by pre-filters."""
    return {
        "title": "Data Analytics Intern",
        "company": "Google",
        "location": "Mountain View, CA",
        "url": "https://boards.greenhouse.io/google/jobs/11111",
        "ats": "greenhouse",
        "slug": "google",
        "skill_level": "intern",
        "is_recruiter": False,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def recruiter_job():
    """Should be filtered out when exclude_recruiters=True."""
    return {
        "title": "BI Analyst",
        "company": "StaffingSolutions",
        "location": "Phoenix, AZ",
        "url": "https://boards.greenhouse.io/staffingsolutions/jobs/22222",
        "ats": "greenhouse",
        "slug": "staffingsolutions",
        "skill_level": "mid",
        "is_recruiter": True,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def remote_job():
    """Remote job — location_match should be 1.0."""
    return {
        "title": "Analytics Engineer",
        "company": "Databricks",
        "location": "Remote",
        "url": "https://boards.greenhouse.io/databricks/jobs/33333",
        "ats": "greenhouse",
        "slug": "databricks",
        "skill_level": "mid",
        "is_recruiter": False,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def missing_fields_job():
    """Job with minimal fields — should score with defaults, not crash."""
    return {
        "url": "https://example.com/job/44444",
    }


@pytest.fixture
def sample_jobs(p1_job, p1_job_alt, p4_job, intern_job, recruiter_job, remote_job):
    """A mixed bag of jobs for testing pipelines."""
    return [p1_job, p1_job_alt, p4_job, intern_job, recruiter_job, remote_job]
