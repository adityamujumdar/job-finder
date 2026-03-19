"""Shared test fixtures — hardcoded profiles for isolation (no file I/O).

Two profile fixtures:
  - bi_profile: BI/Data Analyst (Chandler, AZ, mid level)
  - swe_profile: Backend Software Engineer (Toronto, senior level)
  - profile: alias for bi_profile (backward compat with existing tests)

Job fixtures are keyed to the BI profile by default.
Tests that need the SWE profile use swe_profile explicitly.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_profile


# ── BI/Data Analyst Profile ──────────────────────────────────────────────────

BI_PROFILE_RAW = {
    "name": "Test User BI",
    "location": "Chandler, AZ",
    "willing_to_relocate": True,
    "relocation_cities": [
        "San Francisco, CA",
        "Seattle, WA",
        "New York, NY",
        "Austin, TX",
        "Denver, CO",
    ],
    "remote_ok": True,
    "years_experience": 5,
    "target_level": "mid",
    "exclude_levels": ["intern"],
    "target_roles": [
        "Business Intelligence",
        "BI Developer",
        "BI Engineer",
        "BI Analyst",
        "Data Analyst",
        "Business Analyst",
        "Analytics Engineer",
        "Data Engineer",
        "Analytics Manager",
        "Business Intelligence Manager",
    ],
    "skills": [
        "Python", "SQL", "Tableau", "Power BI", "Azure", "R", "VBA",
        "Oracle SQL", "SPSS", "Google Analytics", "Adobe Analytics",
        "Kibana", "ETL", "Machine Learning", "Financial Modeling",
    ],
    "boost_keywords": [
        "analytics", "intelligence", "reporting", "dashboard",
        "visualization", "data", "insights", "forecast",
    ],
    "preferred_companies": {
        "greenhouse": ["anthropic", "figma", "stripe", "notion", "databricks",
                        "snowflakecomputing", "plaid", "brex", "ramp"],
        "lever": ["twitch"],
        "workday": ["nvidia|wd5|NVIDIAExternalCareerSite", "intel|wd1|External"],
        "ashby": ["1password", "linear"],
    },
    "exclude_recruiters": True,
    "exclude_staffing": True,
    "exclude_title_patterns": [],
    "metro_cities": [
        "Phoenix", "Tempe", "Scottsdale", "Mesa", "Gilbert",
        "Glendale", "Peoria", "Surprise",
    ],
}


# ── Backend SWE Profile ──────────────────────────────────────────────────────

SWE_PROFILE_RAW = {
    "name": "Test User SWE",
    "location": "Toronto, Canada",
    "willing_to_relocate": True,
    "relocation_cities": [
        "Toronto, ON",
        "Vancouver, BC",
        "Montreal, QC",
        "Waterloo, ON",
    ],
    "remote_ok": True,
    "years_experience": 9,
    "target_level": "senior",
    "exclude_levels": ["intern"],
    "target_roles": [
        "Backend Engineer",
        "Backend Software Engineer",
        "Software Engineer",
        "Software Developer",
        "Senior Software Engineer",
        "Senior Software Developer",
        "Platform Engineer",
        "Systems Engineer",
        "Infrastructure Engineer",
    ],
    "skills": [
        "Java", "Kotlin", "Python", "TypeScript", "SQL",
        "Spring Boot", "REST APIs", "Microservices", "Distributed Systems",
        "AWS", "DynamoDB", "Docker", "CI/CD",
    ],
    "boost_keywords": [
        "backend", "distributed", "microservices", "api",
        "infrastructure", "platform", "cloud", "scalable",
        "java", "kotlin", "spring",
    ],
    "preferred_companies": {
        "greenhouse": ["stripe", "anthropic", "shopify"],
        "ashby": ["1password", "linear"],
    },
    "exclude_recruiters": True,
    "exclude_staffing": True,
    "exclude_title_patterns": [
        "cloud platform", "cloud infrastructure", "devops", "sre",
        "site reliability",
    ],
    "metro_cities": [
        "Mississauga", "Brampton", "Markham", "Scarborough", "Vaughan",
    ],
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def bi_profile():
    """Hardcoded BI/Data Analyst profile — no file I/O."""
    return load_profile(raw=BI_PROFILE_RAW)


@pytest.fixture
def swe_profile():
    """Hardcoded Backend SWE profile — no file I/O."""
    return load_profile(raw=SWE_PROFILE_RAW)


@pytest.fixture
def profile(bi_profile):
    """Default profile for backward compat — aliases bi_profile."""
    return bi_profile


# ── Job Fixtures (keyed to BI profile) ────────────────────────────────────────

@pytest.fixture
def p1_job():
    """A synthetic job that MUST score P1 (≥85) for the BI profile."""
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
    """Another P1 for BI — Data Analyst in Chandler, AZ at a preferred company."""
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
    """A synthetic job that MUST score P4 (<50) — terrible match for any profile."""
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
    """Remote BI job — should score well for BI profile."""
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


# ── SWE Job Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def swe_p1_job():
    """A synthetic job that MUST score P1 (≥85) for the SWE profile."""
    return {
        "title": "Senior Backend Software Engineer",
        "company": "Stripe",
        "location": "Toronto, Canada",
        "url": "https://boards.greenhouse.io/stripe/jobs/55555",
        "ats": "greenhouse",
        "company_slug": "stripe",
        "skill_level": "senior",
        "is_recruiter": False,
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def sample_jobs(p1_job, p1_job_alt, p4_job, intern_job, recruiter_job, remote_job):
    """A mixed bag of jobs for testing pipelines."""
    return [p1_job, p1_job_alt, p4_job, intern_job, recruiter_job, remote_job]
