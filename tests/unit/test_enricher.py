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
