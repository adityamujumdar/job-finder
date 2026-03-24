"""Unit tests for src/enricher.py — description fetching and skill extraction.

Tests are isolated: no real HTTP calls, no file I/O beyond temp paths.
All ATS fetch functions are tested via mocking. Extraction logic is tested
directly since it's pure functions.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.enricher import (
    detect_ats,
    extract_greenhouse_info,
    extract_lever_info,
    extract_ashby_info,
    extract_skills,
    extract_salary,
    compute_skill_match_pct,
    _html_to_text,
    _is_login_page,
    _is_expired_page,
    fetch_workday_playwright,
    fetch_with_browser,
    fetch_greenhouse,
    fetch_lever,
    fetch_ashby,
    enrich_job,
    run_enricher,
    MIN_DESCRIPTION_CHARS,
    EXPIRED_MAX_CHARS,
)
from src.matcher import blend_enriched_score


# ── ATS Detection ─────────────────────────────────────────────────────────────

class TestDetectATS:
    def test_greenhouse(self):
        assert detect_ats({"ats": "Greenhouse"}) == "greenhouse"

    def test_lever(self):
        assert detect_ats({"ats": "Lever"}) == "lever"

    def test_ashby(self):
        assert detect_ats({"ats": "Ashby"}) == "ashby"

    def test_workday(self):
        assert detect_ats({"ats": "Workday"}) == "workday"

    def test_bamboohr(self):
        assert detect_ats({"ats": "BambooHR"}) == "bamboohr"

    def test_unknown(self):
        assert detect_ats({"ats": "unknownboard"}) == "unknown"

    def test_empty(self):
        assert detect_ats({}) == "unknown"


# ── URL Parsing ───────────────────────────────────────────────────────────────

class TestExtractGreenhouseInfo:
    def test_standard_boards_url(self):
        url = "https://boards.greenhouse.io/anthropic/jobs/4982198008"
        slug, job_id = extract_greenhouse_info(url)
        assert slug == "anthropic"
        assert job_id == "4982198008"

    def test_job_boards_url(self):
        url = "https://job-boards.greenhouse.io/narvar/jobs/7415441"
        slug, job_id = extract_greenhouse_info(url)
        assert slug == "narvar"
        assert job_id == "7415441"

    def test_hosted_board_gh_jid(self):
        # Stripe uses hosted board with gh_jid query param
        url = "https://stripe.com/jobs/search?gh_jid=6042172"
        result = extract_greenhouse_info(url)
        assert result is not None
        slug, job_id = result
        assert job_id == "6042172"

    def test_custom_hosted_gh_jid(self):
        url = "https://careers.acme.com/position?gh_jid=12345"
        result = extract_greenhouse_info(url)
        assert result is not None
        _, job_id = result
        assert job_id == "12345"

    def test_unrecognized_url(self):
        assert extract_greenhouse_info("https://linkedin.com/jobs/123") is None

    def test_none_url(self):
        assert extract_greenhouse_info("") is None


class TestExtractLeverInfo:
    def test_standard_lever_url(self):
        url = "https://jobs.lever.co/stripe/abc-123-def"
        slug, job_id = extract_lever_info(url)
        assert slug == "stripe"
        assert job_id == "abc-123-def"

    def test_unrecognized_url(self):
        assert extract_lever_info("https://greenhouse.io/jobs/123") is None


class TestExtractAshbyInfo:
    def test_standard_ashby_url(self):
        url = "https://jobs.ashbyhq.com/linear/abc-123"
        slug, job_id = extract_ashby_info(url)
        assert slug == "linear"
        assert job_id == "abc-123"

    def test_unrecognized_url(self):
        assert extract_ashby_info("https://lever.co/jobs/123") is None


# ── Text Processing ───────────────────────────────────────────────────────────

class TestHtmlToText:
    def test_strips_html_tags(self):
        html = "<h2>Requirements</h2><ul><li>Java experience</li><li>AWS</li></ul>"
        text = _html_to_text(html)
        assert "Requirements" in text
        assert "Java experience" in text
        assert "<" not in text

    def test_unescapes_html_entities(self):
        # Greenhouse returns double-encoded HTML
        escaped = "&lt;p&gt;Java &amp; AWS experience&lt;/p&gt;"
        text = _html_to_text(escaped)
        assert "Java" in text
        assert "AWS" in text
        assert "&lt;" not in text

    def test_empty_input(self):
        assert _html_to_text("") == ""


# ── Skill Extraction ──────────────────────────────────────────────────────────

SAMPLE_JD_REQUIRED_ONLY = """
Backend Engineer — Requirements

Required qualifications:
- 5+ years of Java or Kotlin experience
- Strong background in AWS (Lambda, SQS, DynamoDB)
- Experience with Spring Boot and RESTful APIs
- SQL proficiency

We work in a fast-paced environment.
"""

SAMPLE_JD_WITH_NICE = """
Senior Software Engineer

What you'll need (required):
- Java development experience (5+ years)
- AWS cloud services knowledge
- Spring Boot expertise

Nice to have:
- Go programming experience
- Terraform knowledge
"""


class TestExtractSkills:
    SKILLS = ["Java", "Kotlin", "Python", "AWS", "Spring Boot", "DynamoDB", "SQL", "Go", "Terraform"]

    def test_finds_required_skills(self):
        result = extract_skills(SAMPLE_JD_REQUIRED_ONLY, self.SKILLS)
        assert "Java" in result["required"] or "Kotlin" in result["required"]
        assert "AWS" in result["required"]

    def test_separates_nice_to_have(self):
        result = extract_skills(SAMPLE_JD_WITH_NICE, self.SKILLS)
        assert "Java" in result["required"]
        assert "AWS" in result["required"]
        assert "Go" in result["nice_to_have"]

    def test_empty_description(self):
        result = extract_skills("", self.SKILLS)
        assert result == {"required": [], "nice_to_have": []}

    def test_empty_skills(self):
        result = extract_skills(SAMPLE_JD_REQUIRED_ONLY, [])
        assert result == {"required": [], "nice_to_have": []}

    def test_no_skills_present(self):
        jd = "We are looking for a passionate person to join our team. Great culture!"
        result = extract_skills(jd, self.SKILLS)
        assert result["required"] == []
        assert result["nice_to_have"] == []

    def test_case_insensitive_matching(self):
        jd = "REQUIRED: JAVA developer with AWS experience"
        result = extract_skills(jd, ["Java", "AWS"])
        assert "Java" in result["required"]
        assert "AWS" in result["required"]


# ── Salary Extraction ─────────────────────────────────────────────────────────

class TestExtractSalary:
    def test_usd_range(self):
        text = "Base salary: $180,000–$220,000 annually"
        salary = extract_salary(text)
        assert salary is not None
        assert "180" in salary

    def test_k_notation(self):
        text = "Compensation range: $180K - $220K"
        salary = extract_salary(text)
        assert salary is not None

    def test_cad_range(self):
        text = "CAD 120,000 to 150,000 per year"
        salary = extract_salary(text)
        assert salary is not None

    def test_no_salary(self):
        text = "We offer competitive compensation and excellent benefits."
        assert extract_salary(text) is None

    def test_empty_text(self):
        assert extract_salary("") is None


# ── Skill Match Percentage ────────────────────────────────────────────────────

class TestComputeSkillMatchPct:
    def test_full_match(self):
        assert compute_skill_match_pct(["Java", "AWS"], ["Java", "AWS", "Python"]) == 100

    def test_partial_match(self):
        pct = compute_skill_match_pct(["Java", "Go", "Rust"], ["Java", "Python"])
        assert pct == 33  # 1/3 = 33%

    def test_zero_match(self):
        assert compute_skill_match_pct(["Go", "Rust"], ["Java", "Python"]) == 0

    def test_empty_required(self):
        # No required skills found → can't compute → return 0
        assert compute_skill_match_pct([], ["Java", "Python"]) == 0

    def test_case_insensitive(self):
        assert compute_skill_match_pct(["java", "aws"], ["Java", "AWS"]) == 100


# ── Score Blending ────────────────────────────────────────────────────────────

class TestBlendEnrichedScore:
    def test_full_skill_match_boosts_score(self):
        # 100% skill match should pull score up
        blended = blend_enriched_score(title_score=70, skill_match_pct=100)
        assert blended > 70

    def test_zero_skill_match_drags_score(self):
        # 0% skill match should pull score down
        blended = blend_enriched_score(title_score=90, skill_match_pct=0)
        assert blended < 90

    def test_exact_calculation(self):
        # 0.70 × 80 + 0.30 × 60 = 56 + 18 = 74
        blended = blend_enriched_score(title_score=80, skill_match_pct=60)
        assert abs(blended - 74.0) < 0.1

    def test_matcher_import_works(self):
        result = blend_enriched_score(80, 100)
        assert result > 80

    def test_score_clamped_to_range(self):
        # Both inputs are 0-100, output should be 0-100
        high = blend_enriched_score(100, 100)
        low = blend_enriched_score(0, 0)
        assert 0 <= low <= 100
        assert 0 <= high <= 100


# ── Login Page Detection ─────────────────────────────────────────────────────

class TestIsLoginPage:
    def test_detects_workday_login(self):
        text = "Sign In to Your Account\nCreate Account\nForgot Password"
        assert _is_login_page(text) is True

    def test_does_not_flag_job_description(self):
        text = "We are hiring a Software Engineer. Sign up for our newsletter."
        assert _is_login_page(text) is False

    def test_requires_two_markers(self):
        # Only one marker — should NOT be flagged
        text = "Sign in to apply for this position. Java required."
        assert _is_login_page(text) is False


# ── Expired Page Detection ───────────────────────────────────────────────────

class TestIsExpiredPage:
    """Content-based detection of expired/dead job listing pages.

    Workday (and other ATS) return HTTP 200 for expired jobs with a short
    message. The function detects these via marker phrases + length gate.
    """

    def test_detects_workday_expired(self):
        text = "The job is no longer available. Please search for other opportunities."
        assert _is_expired_page(text) is True

    def test_detects_filled_position(self):
        text = "This position has been filled. Thank you for your interest."
        assert _is_expired_page(text) is True

    def test_detects_closed_job(self):
        text = "This job is closed. View similar jobs on our careers page."
        assert _is_expired_page(text) is True

    def test_detects_no_longer_accepting(self):
        text = "This role is no longer accepting applications."
        assert _is_expired_page(text) is True

    def test_does_not_flag_real_job_description(self):
        """A real JD should never be flagged as expired."""
        text = (
            "About the Role\n"
            "We are looking for a Senior Software Engineer to join our platform team.\n"
            "Requirements: Java, Python, AWS, 5+ years experience.\n"
            "This is a full-time position based in San Francisco.\n"
        ) * 5  # make it >100 chars but still reasonable
        assert _is_expired_page(text) is False

    def test_long_page_with_expired_phrase_is_not_flagged(self):
        """A long JD that incidentally mentions 'position has been filled' should NOT
        be flagged — the length gate prevents false positives."""
        text = (
            "We are hiring a Software Engineer. " * 50
            + "Once this position has been filled, the team will expand to 10 people. "
            + "Requirements: Java, Python, AWS. " * 20
        )
        assert len(text) > EXPIRED_MAX_CHARS  # verify it's long
        assert _is_expired_page(text) is False

    def test_short_text_without_markers_is_not_flagged(self):
        """Short text without expired markers should not be flagged."""
        text = "Loading... please wait."
        assert _is_expired_page(text) is False

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        text = "THE JOB IS NO LONGER AVAILABLE"
        assert _is_expired_page(text) is True

    def test_real_workday_expired_page(self):
        """Exact text from a real dead Workday job page (HTTP 200, JS-rendered).

        URL: https://workday.wd5.myworkdayjobs.com/workday/job/USA-CA-Pleasanton/
             People-Analytics-Data-Scientist_JR-0104261-1
        Workday returns a generic "page doesn't exist" page for taken-down jobs.
        """
        text = (
            "Skip to main contentCareers at WorkdayEnglishSign InCareers Page"
            "Search for JobsJoin Our Talent Community!\n\n"
            "The page you are looking for doesn't exist."
            "Search for JobsFollow UsRecruitment Privacy Statement"
            "\u00a9 2026 Workday, Inc. All rights reserved."
        )
        assert _is_expired_page(text) is True


# ── Lever Tuple Return ───────────────────────────────────────────────────────

class TestFetchLeverTuple:
    @patch("src.enricher._http_get")
    def test_expired_job_returns_tuple(self, mock_http):
        """404 response returns (None, True) for expired."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http.return_value = mock_response

        text, expired = fetch_lever("netflix", "abc-123")
        assert text is None
        assert expired is True

    @patch("src.enricher._http_get")
    def test_success_returns_tuple(self, mock_http):
        """200 response returns (text, False)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "descriptionPlain": "Java and AWS required. " * 10,
        }
        mock_http.return_value = mock_response

        text, expired = fetch_lever("netflix", "abc-123")
        assert text is not None
        assert "Java" in text
        assert expired is False

    @patch("src.enricher._http_get")
    def test_network_error_returns_tuple(self, mock_http):
        """None response returns (None, False)."""
        mock_http.return_value = None

        text, expired = fetch_lever("netflix", "abc-123")
        assert text is None
        assert expired is False


# ── Ashby Tuple Return ───────────────────────────────────────────────────────

class TestFetchAshbyTuple:
    @patch("src.enricher._http_get")
    def test_expired_job_returns_tuple(self, mock_http):
        """404 response returns (None, True) for expired."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http.return_value = mock_response

        text, expired = fetch_ashby("anthropic", "abc-123")
        assert text is None
        assert expired is True

    @patch("src.enricher._http_get")
    def test_success_returns_tuple(self, mock_http):
        """200 response returns (text, False)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "descriptionPlain": "Python and Kubernetes required. " * 10,
        }
        mock_http.return_value = mock_response

        text, expired = fetch_ashby("anthropic", "abc-123")
        assert text is not None
        assert "Python" in text
        assert expired is False

    @patch("src.enricher._http_get")
    def test_network_error_returns_tuple(self, mock_http):
        """None response returns (None, False)."""
        mock_http.return_value = None

        text, expired = fetch_ashby("anthropic", "abc-123")
        assert text is None
        assert expired is False


# ── Expired Content Detection in enrich_job ──────────────────────────────────

class TestEnrichJobExpiredContent:
    """Tests that enrich_job marks jobs as expired when the page content
    indicates the job is no longer available (especially Workday)."""

    @patch("src.enricher.fetch_with_browser")
    def test_workday_expired_page_marked_expired(self, mock_fetch):
        """Workday page returning 'job no longer available' text should be expired."""
        mock_fetch.return_value = "The job is no longer available. Please search for other opportunities."
        job = {"url": "https://company.wd5.myworkdayjobs.com/job/123", "ats": "Workday"}
        profile = {"skills": ["Java"]}

        result = enrich_job(job, profile, browser=MagicMock())
        assert result["expired"] is True
        assert result.get("unenriched") is False

    @patch("src.enricher.fetch_with_browser")
    def test_workday_valid_page_not_expired(self, mock_fetch):
        """Workday page with real JD should NOT be marked expired."""
        mock_fetch.return_value = "Java and AWS experience required. " * 20
        job = {"url": "https://company.wd5.myworkdayjobs.com/job/123", "ats": "Workday"}
        profile = {"skills": ["Java", "AWS"]}

        result = enrich_job(job, profile, browser=MagicMock())
        assert result["expired"] is False
        assert result.get("unenriched") is False

    @patch("src.enricher.fetch_with_browser")
    def test_real_workday_doesnt_exist_page(self, mock_fetch):
        """Real Workday 'page doesn't exist' text should mark job as expired.

        This is the exact text returned by Playwright for:
        https://workday.wd5.myworkdayjobs.com/workday/job/USA-CA-Pleasanton/
        People-Analytics-Data-Scientist_JR-0104261-1
        """
        mock_fetch.return_value = (
            "Skip to main contentCareers at WorkdayEnglishSign InCareers Page"
            "Search for JobsJoin Our Talent Community!\n\n"
            "The page you are looking for doesn't exist."
            "Search for JobsFollow UsRecruitment Privacy Statement"
            "\u00a9 2026 Workday, Inc. All rights reserved."
        )
        job = {
            "url": "https://workday.wd5.myworkdayjobs.com/workday/job/USA-CA-Pleasanton/"
                   "People-Analytics-Data-Scientist_JR-0104261-1",
            "ats": "Workday",
        }
        profile = {"skills": ["Python", "SQL"]}

        result = enrich_job(job, profile, browser=MagicMock())
        assert result["expired"] is True
        assert result.get("unenriched") is False
        # Should NOT have extracted any skills from the error page boilerplate
        assert "skills_required" not in result


# ── Playwright Fetch ─────────────────────────────────────────────────────────

class TestFetchWorkdayPlaywright:
    def test_happy_path(self):
        """Playwright returns a valid job description."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_element = MagicMock()

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.query_selector.return_value = mock_element
        mock_element.text_content.return_value = "X" * 200  # > MIN_DESCRIPTION_CHARS

        result = fetch_workday_playwright("https://company.wd5.myworkdayjobs.com/job/123", mock_browser)
        assert result is not None
        assert len(result) >= MIN_DESCRIPTION_CHARS
        mock_context.close.assert_called()

    def test_returns_none_when_browser_is_none(self):
        """Playwright not available — returns None gracefully."""
        result = fetch_workday_playwright("https://company.wd5.myworkdayjobs.com/job/123", None)
        assert result is None

    def test_returns_none_on_timeout(self):
        """Playwright times out — returns None, context is cleaned up."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.goto.side_effect = Exception("Timeout exceeded")

        result = fetch_workday_playwright("https://company.wd5.myworkdayjobs.com/job/123", mock_browser)
        assert result is None
        mock_context.close.assert_called()

    def test_detects_login_page(self):
        """Login page detected — returns None instead of wrong content."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_element = MagicMock()

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.query_selector.return_value = mock_element
        # Return login page content (>100 chars but contains login markers)
        login_text = "Sign In to Your Workday Account " * 10 + " Create Account Forgot Password"
        mock_element.text_content.return_value = login_text

        result = fetch_workday_playwright("https://company.wd5.myworkdayjobs.com/job/123", mock_browser)
        assert result is None

    def test_short_text_returns_none(self):
        """Page returns too little text — returns None."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_element = MagicMock()

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.query_selector.return_value = mock_element
        mock_element.text_content.return_value = "Loading..."  # < 100 chars

        # Also set up networkidle fallback to return short text
        mock_page.text_content.return_value = "Loading..."

        result = fetch_workday_playwright("https://company.wd5.myworkdayjobs.com/job/123", mock_browser)
        assert result is None


# ── fetch_with_browser Fallback Chain ────────────────────────────────────────

class TestFetchWithBrowser:
    @patch("src.enricher.fetch_workday_playwright")
    @patch("src.enricher.fetch_via_browse")
    def test_playwright_succeeds_skips_gstack(self, mock_browse, mock_pw):
        """When Playwright succeeds, gstack is not called."""
        mock_pw.return_value = "Valid description text " * 10
        mock_browse.return_value = "Should not be called"

        result = fetch_with_browser("https://example.com/job/123", browser=MagicMock())
        assert result is not None
        mock_browse.assert_not_called()

    @patch("src.enricher.fetch_workday_playwright")
    @patch("src.enricher.fetch_via_browse")
    def test_playwright_fails_gstack_succeeds(self, mock_browse, mock_pw):
        """When Playwright fails, falls back to gstack."""
        mock_pw.return_value = None
        mock_browse.return_value = "Fallback description " * 10

        result = fetch_with_browser("https://example.com/job/123", browser=MagicMock())
        assert result is not None
        assert "Fallback" in result

    @patch("src.enricher.fetch_workday_playwright")
    @patch("src.enricher.fetch_via_browse")
    def test_both_fail_returns_none(self, mock_browse, mock_pw):
        """When both Playwright and gstack fail, returns None."""
        mock_pw.return_value = None
        mock_browse.return_value = None

        result = fetch_with_browser("https://example.com/job/123", browser=MagicMock())
        assert result is None


# ── Greenhouse Tuple Return ──────────────────────────────────────────────────

class TestFetchGreenhouseTuple:
    @patch("src.enricher._http_get")
    def test_expired_job_returns_tuple(self, mock_http):
        """404 response returns (None, True) for expired."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http.return_value = mock_response

        text, expired = fetch_greenhouse("anthropic", "9999999")
        assert text is None
        assert expired is True

    @patch("src.enricher._http_get")
    def test_success_returns_tuple(self, mock_http):
        """200 response returns (text, False)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "<p>Java and AWS required</p>"}
        mock_http.return_value = mock_response

        text, expired = fetch_greenhouse("anthropic", "123456")
        assert text is not None
        assert "Java" in text
        assert expired is False

    @patch("src.enricher._http_get")
    def test_network_error_returns_tuple(self, mock_http):
        """None response returns (None, False)."""
        mock_http.return_value = None

        text, expired = fetch_greenhouse("anthropic", "123456")
        assert text is None
        assert expired is False


# ── enrich_job with browser param ────────────────────────────────────────────

class TestEnrichJobWithBrowser:
    @patch("src.enricher.fetch_with_browser")
    def test_workday_job_uses_fetch_with_browser(self, mock_fetch):
        """Workday jobs route through fetch_with_browser."""
        mock_fetch.return_value = "Java and AWS experience required. " * 10
        job = {"url": "https://company.wd5.myworkdayjobs.com/job/123", "ats": "Workday"}
        profile = {"skills": ["Java", "AWS"]}
        mock_browser = MagicMock()

        result = enrich_job(job, profile, browser=mock_browser)
        assert result["unenriched"] is False
        mock_fetch.assert_called_once_with(
            "https://company.wd5.myworkdayjobs.com/job/123", mock_browser
        )

    @patch("src.enricher.fetch_with_browser")
    def test_unknown_ats_uses_fetch_with_browser(self, mock_fetch):
        """Unknown ATS jobs also route through fetch_with_browser."""
        mock_fetch.return_value = None
        job = {"url": "https://careers.example.com/job/123", "ats": "custom"}
        profile = {"skills": ["Java"]}

        result = enrich_job(job, profile, browser=None)
        assert result["unenriched"] is True
        mock_fetch.assert_called_once()


# ── Incremental Enrichment Skip ─────────────────────────────────────────────

class TestIncrementalSkip:
    """Tests for incremental enrichment — skipping already-enriched jobs."""

    @patch("src.enricher.enrich_job")
    @patch("src.enricher.load_profile")
    def test_skips_recently_enriched_jobs(self, mock_profile, mock_enrich, tmp_path):
        """Jobs enriched within 7 days are skipped."""
        from datetime import datetime, timezone

        mock_profile.return_value = {"skills": ["Java"]}

        scored_dir = tmp_path / "scored"
        enriched_dir = tmp_path / "enriched"
        scored_dir.mkdir()
        enriched_dir.mkdir()

        # Write scored data with 2 jobs
        jobs = [
            {"url": "https://a.com/1", "ats": "Greenhouse", "_priority": "P1", "_score": 90},
            {"url": "https://b.com/2", "ats": "Lever", "_priority": "P1", "_score": 80},
        ]
        (scored_dir / "2026-03-22.json").write_text(json.dumps(jobs))

        # Write existing enriched data — job A was enriched recently
        existing = {
            "https://a.com/1": {
                "url": "https://a.com/1",
                "unenriched": False,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        (enriched_dir / "2026-03-22.json").write_text(json.dumps(existing))

        # Mock enrich_job to return unenriched for any call
        mock_enrich.return_value = {"url": "https://b.com/2", "unenriched": True, "expired": False, "fetched_at": datetime.now(timezone.utc).isoformat()}

        with patch("src.enricher.SCORED_DIR", scored_dir), \
             patch("src.enricher.ENRICHED_DIR", enriched_dir), \
             patch("src.enricher.ensure_dirs"):
            result = run_enricher(date="2026-03-22")

        assert result["skipped"] == 1
        # Only job B should have been submitted to enrich_job
        assert mock_enrich.call_count == 1

    @patch("src.enricher.enrich_job")
    @patch("src.enricher.load_profile")
    def test_does_not_skip_unenriched_jobs(self, mock_profile, mock_enrich, tmp_path):
        """Jobs that were previously unenriched are retried."""
        from datetime import datetime, timezone

        mock_profile.return_value = {"skills": ["Java"]}

        scored_dir = tmp_path / "scored"
        enriched_dir = tmp_path / "enriched"
        scored_dir.mkdir()
        enriched_dir.mkdir()

        jobs = [
            {"url": "https://a.com/1", "ats": "Greenhouse", "_priority": "P1", "_score": 90},
        ]
        (scored_dir / "2026-03-22.json").write_text(json.dumps(jobs))

        # Previously unenriched — should be retried
        existing = {
            "https://a.com/1": {
                "url": "https://a.com/1",
                "unenriched": True,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        (enriched_dir / "2026-03-22.json").write_text(json.dumps(existing))

        mock_enrich.return_value = {"url": "https://a.com/1", "unenriched": True, "expired": False, "fetched_at": datetime.now(timezone.utc).isoformat()}

        with patch("src.enricher.SCORED_DIR", scored_dir), \
             patch("src.enricher.ENRICHED_DIR", enriched_dir), \
             patch("src.enricher.ensure_dirs"):
            result = run_enricher(date="2026-03-22")

        assert result["skipped"] == 0
        assert mock_enrich.call_count == 1

    @patch("src.enricher.enrich_job")
    @patch("src.enricher.load_profile")
    def test_does_not_skip_stale_enrichment(self, mock_profile, mock_enrich, tmp_path):
        """Jobs enriched more than 7 days ago are re-enriched."""
        from datetime import datetime, timezone, timedelta

        mock_profile.return_value = {"skills": ["Java"]}

        scored_dir = tmp_path / "scored"
        enriched_dir = tmp_path / "enriched"
        scored_dir.mkdir()
        enriched_dir.mkdir()

        jobs = [
            {"url": "https://a.com/1", "ats": "Greenhouse", "_priority": "P1", "_score": 90},
        ]
        (scored_dir / "2026-03-22.json").write_text(json.dumps(jobs))

        # Enriched 10 days ago — should be re-enriched
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        existing = {
            "https://a.com/1": {
                "url": "https://a.com/1",
                "unenriched": False,
                "fetched_at": old_date,
            }
        }
        (enriched_dir / "2026-03-22.json").write_text(json.dumps(existing))

        mock_enrich.return_value = {"url": "https://a.com/1", "unenriched": False, "skills_required": ["Java"], "fetched_at": datetime.now(timezone.utc).isoformat()}

        with patch("src.enricher.SCORED_DIR", scored_dir), \
             patch("src.enricher.ENRICHED_DIR", enriched_dir), \
             patch("src.enricher.ensure_dirs"):
            result = run_enricher(date="2026-03-22")

        assert result["skipped"] == 0
        assert mock_enrich.call_count == 1
