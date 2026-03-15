"""Unit tests for vendored JBA fetcher — no network calls."""

from src.jba_fetcher import (
    job_tier_classification, is_recruiter_company,
    get_dedup_key, get_composite_key, clean_job_data,
)


class TestJobTierClassification:
    def test_senior(self):
        assert job_tier_classification("Senior Data Engineer") == "senior"

    def test_sr_dot(self):
        assert job_tier_classification("Sr. Business Analyst") == "senior"

    def test_lead(self):
        assert job_tier_classification("Lead Analytics Engineer") == "senior"

    def test_manager(self):
        assert job_tier_classification("Analytics Manager") == "senior"

    def test_mid(self):
        assert job_tier_classification("Data Analyst") == "mid"

    def test_junior(self):
        assert job_tier_classification("Junior Data Analyst") == "entry"

    def test_intern(self):
        assert job_tier_classification("Data Analytics Intern") == "intern"

    def test_internship(self):
        assert job_tier_classification("Summer Internship - BI") == "intern"

    def test_entry_level(self):
        assert job_tier_classification("Entry-Level Business Analyst") == "entry"

    def test_director(self):
        assert job_tier_classification("Director of Analytics") == "senior"

    def test_principal(self):
        assert job_tier_classification("Principal Data Scientist") == "senior"


class TestIsRecruiterCompany:
    def test_recruiter(self):
        assert is_recruiter_company("staffingsolutions") is True

    def test_recruiting(self):
        assert is_recruiter_company("techrecruiting") is True

    def test_talent(self):
        assert is_recruiter_company("talentgroup") is True

    def test_not_recruiter(self):
        assert is_recruiter_company("anthropic") is False

    def test_not_recruiter_stripe(self):
        assert is_recruiter_company("stripe") is False


class TestDedupKey:
    def test_url_based(self):
        job = {"url": "https://boards.greenhouse.io/anthropic/jobs/12345", "ats": "Greenhouse"}
        assert get_dedup_key(job) == "https://boards.greenhouse.io/anthropic/jobs/12345"

    def test_workday_composite(self):
        job = {"url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/jobs/123", "ats": "Workday", "company": "nvidia"}
        key = get_dedup_key(job)
        assert key == "workday:nvidia:123"

    def test_workday_no_id(self):
        job = {"url": "https://nvidia.wd5.myworkdayjobs.com/site", "ats": "Workday", "company": "nvidia"}
        key = get_dedup_key(job)
        assert key == "https://nvidia.wd5.myworkdayjobs.com/site"


class TestCompositeKey:
    def test_greenhouse(self):
        job = {"url": "https://boards.greenhouse.io/anthropic/jobs/12345", "ats": "Greenhouse", "company_slug": "anthropic"}
        key = get_composite_key(job)
        assert key == "greenhouse:anthropic:12345"

    def test_ashby(self):
        job = {"url": "https://jobs.ashbyhq.com/1password/abc-123-def", "ats": "Ashby", "company_slug": "1password"}
        key = get_composite_key(job)
        assert key == "ashby:1password:abc-123-def"

    def test_lever(self):
        job = {"url": "https://jobs.lever.co/netflix/abc-def-123", "ats": "Lever", "company_slug": "netflix"}
        key = get_composite_key(job)
        assert key == "lever:netflix:abc-def-123"

    def test_no_url(self):
        job = {"ats": "Greenhouse", "company_slug": "test"}
        assert get_composite_key(job) == ""

    def test_catches_url_mismatch(self):
        """Two jobs with different URLs but same composite key = same job."""
        job_a = {"url": "https://boards.greenhouse.io/anthropic/jobs/12345", "ats": "Greenhouse", "company_slug": "anthropic"}
        job_b = {"url": "https://job-boards.greenhouse.io/anthropic/jobs/12345", "ats": "Greenhouse", "company_slug": "anthropic"}
        assert get_composite_key(job_a) == get_composite_key(job_b)
        # But URL-based keys differ
        assert get_dedup_key(job_a) != get_dedup_key(job_b)


class TestCleanJobData:
    def test_removes_no_title(self):
        jobs = [{"title": "", "url": "http://x", "company": "y"}]
        assert len(clean_job_data(jobs)) == 0

    def test_removes_no_url(self):
        jobs = [{"title": "Engineer", "company": "y"}]
        assert len(clean_job_data(jobs)) == 0

    def test_removes_no_company(self):
        jobs = [{"title": "Engineer", "url": "http://x"}]
        assert len(clean_job_data(jobs)) == 0

    def test_keeps_valid(self):
        jobs = [{"title": "Engineer", "url": "http://x", "company": "y"}]
        assert len(clean_job_data(jobs)) == 1
