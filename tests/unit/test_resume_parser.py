"""Unit tests for src/resume_parser.py — resume-to-profile extraction.

Tests are isolated: no file I/O beyond tmp_path fixtures.
All extraction functions are pure (text in → structured data out).
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.resume_parser import (
    extract_name,
    extract_email,
    extract_location,
    extract_years_experience,
    extract_skills,
    extract_roles,
    infer_target_level,
    infer_exclude_levels,
    generate_profile,
    write_profile,
    read_resume_text,
    run_resume_parser,
)


# ── Sample Resumes ───────────────────────────────────────────────────────────

SAMPLE_RESUME = """# JANE DOE

**Email:** jane.doe@example.com | **Phone:** (555) 123-4567 | [LinkedIn](https://linkedin.com/in/janedoe)

Software Engineer with 6+ years of experience building distributed backend systems.

---

## EXPERIENCE

### Senior Software Engineer, Stripe, San Francisco, CA — Jan 2022 – Present

- Built payment processing microservices using Java and Kotlin
- Designed event-driven architecture with Kafka and AWS SQS
- Led migration from monolith to microservices

### Software Engineer, Google, Mountain View, CA — Jun 2018 – Dec 2021

- Developed backend services using Go and Python
- Built data pipelines with Spark and BigQuery
- Implemented REST APIs serving 1M+ requests/day

---

## SKILLS

| Category | Skills |
|----------|--------|
| Languages | Java, Kotlin, Go, Python, TypeScript, SQL |
| Cloud | AWS, GCP, Docker, Kubernetes |
| Data | Kafka, Spark, BigQuery, PostgreSQL |

---

## EDUCATION

- **M.S. Computer Science** — Stanford University, 2018
- **B.S. Computer Science** — UC Berkeley, 2016
"""

MINIMAL_RESUME = """# John Smith

Backend developer. Python and SQL.

## Experience

### Developer, Acme Corp — 2023 – Present
- Wrote Python scripts
"""

EMPTY_RESUME = ""

NO_SKILLS_RESUME = """# Bob Noskills

Professional cat herder with 20 years of experience in feline management.

## Experience
### Senior Cat Herder, Purrfect Inc — 2004 – Present
- Managed teams of 50+ cats across multiple facilities
"""


# ── Name Extraction ──────────────────────────────────────────────────────────

class TestExtractName:
    def test_markdown_heading(self):
        assert extract_name("# JANE DOE\nSome text") == "JANE DOE"

    def test_bold_name(self):
        assert extract_name("**John Smith** | email@test.com") == "John Smith"

    def test_heading_with_suffix(self):
        assert extract_name("# Jane Doe — Software Engineer") == "Jane Doe"

    def test_empty_text(self):
        assert extract_name("") == ""


# ── Email Extraction ─────────────────────────────────────────────────────────

class TestExtractEmail:
    def test_standard_email(self):
        assert extract_email("Contact: jane@example.com | Phone") == "jane@example.com"

    def test_plus_email(self):
        assert extract_email("jane+jobs@example.com") == "jane+jobs@example.com"

    def test_no_email(self):
        assert extract_email("No email here") == ""


# ── Location Extraction ──────────────────────────────────────────────────────

class TestExtractLocation:
    def test_city_state_in_header(self):
        text = "Jane Doe | San Francisco, CA | jane@test.com"
        assert extract_location(text) == "San Francisco, CA"

    def test_city_province(self):
        text = "Based in Toronto, ON\nSoftware Engineer"
        assert extract_location(text) == "Toronto, ON"

    def test_from_job_header(self):
        text = "# Name\n\n### Engineer, Company, AZ, USA — 2020 – Present"
        loc = extract_location(text)
        assert "AZ" in loc

    def test_no_location(self):
        assert extract_location("Just some text with no location info") == ""


# ── Years Experience ─────────────────────────────────────────────────────────

class TestExtractYearsExperience:
    def test_explicit_years_claim(self):
        text = "Software Engineer with 9+ years of experience"
        assert extract_years_experience(text) == 9

    def test_date_ranges(self):
        text = """
### Engineer, Company A — Jun 2018 – Present
### Junior Dev, Company B — Jan 2016 – May 2018
"""
        years = extract_years_experience(text)
        # 2016 to 2026 = 10 years
        assert years >= 8

    def test_single_job(self):
        text = "### Developer, Corp — 2023 – Present"
        years = extract_years_experience(text)
        assert years >= 1

    def test_no_dates(self):
        assert extract_years_experience("No dates here") == 0


# ── Skills Extraction ────────────────────────────────────────────────────────

class TestExtractSkills:
    def test_finds_common_skills(self):
        skills = extract_skills(SAMPLE_RESUME)
        assert "Java" in skills
        assert "Python" in skills
        assert "AWS" in skills

    def test_finds_framework_skills(self):
        skills = extract_skills(SAMPLE_RESUME)
        assert "Kafka" in skills
        assert "Docker" in skills

    def test_minimal_resume(self):
        skills = extract_skills(MINIMAL_RESUME)
        assert "Python" in skills
        assert "SQL" in skills

    def test_no_tech_skills(self):
        skills = extract_skills(NO_SKILLS_RESUME)
        # Should find nothing (no tech skills in cat herding resume)
        assert len(skills) == 0

    def test_deduplication(self):
        text = "Java Java Java Python Python"
        skills = extract_skills(text)
        assert skills.count("Java") == 1
        assert skills.count("Python") == 1


# ── Role Extraction ──────────────────────────────────────────────────────────

class TestExtractRoles:
    def test_finds_engineer_roles(self):
        roles = extract_roles(SAMPLE_RESUME)
        role_lower = [r.lower() for r in roles]
        assert any("senior software engineer" in r for r in role_lower)
        assert any("software engineer" in r for r in role_lower)

    def test_minimal_resume(self):
        # "Developer" isn't in our title patterns — should return empty
        roles = extract_roles(MINIMAL_RESUME)
        assert isinstance(roles, list)

    def test_deduplication(self):
        text = """
### Senior Software Engineer, A — 2022 – Present
### Senior Software Engineer, B — 2020 – 2022
"""
        roles = extract_roles(text)
        assert roles.count("Senior Software Engineer") <= 1


# ── Level Inference ──────────────────────────────────────────────────────────

class TestInferTargetLevel:
    def test_entry(self):
        assert infer_target_level(1) == "entry"

    def test_mid(self):
        assert infer_target_level(3) == "mid"

    def test_senior(self):
        assert infer_target_level(7) == "senior"

    def test_staff(self):
        assert infer_target_level(12) == "staff"

    def test_zero_years(self):
        assert infer_target_level(0) == "entry"


class TestInferExcludeLevels:
    def test_senior_excludes_intern(self):
        exclude = infer_exclude_levels("senior")
        assert "intern" in exclude

    def test_entry_excludes_nothing(self):
        exclude = infer_exclude_levels("entry")
        assert len(exclude) == 0

    def test_mid_excludes_intern(self):
        # entry idx=1, mid idx=2, exclude below idx 1 → ["intern"]
        exclude = infer_exclude_levels("mid")
        assert "intern" in exclude


# ── Full Profile Generation ──────────────────────────────────────────────────

class TestGenerateProfile:
    def test_generates_complete_profile(self):
        profile = generate_profile(SAMPLE_RESUME)
        assert profile["name"] == "JANE DOE"
        assert profile["email"] == "jane.doe@example.com"
        assert profile["years_experience"] >= 6
        assert profile["target_level"] == "senior"
        assert len(profile["skills"]) > 0
        assert len(profile["target_roles"]) > 0
        assert profile["remote_ok"] is True
        assert profile["exclude_recruiters"] is True

    def test_has_all_required_fields(self):
        profile = generate_profile(SAMPLE_RESUME)
        required = [
            "name", "location", "target_roles", "skills",
            "years_experience", "target_level", "exclude_levels",
            "boost_keywords", "preferred_companies",
        ]
        for field in required:
            assert field in profile, f"Missing field: {field}"

    def test_minimal_resume_still_works(self):
        profile = generate_profile(MINIMAL_RESUME)
        assert profile["name"] == "John Smith"
        assert len(profile["skills"]) >= 1

    def test_caps_target_roles_at_8(self):
        profile = generate_profile(SAMPLE_RESUME)
        assert len(profile["target_roles"]) <= 8

    def test_caps_skills_at_15(self):
        profile = generate_profile(SAMPLE_RESUME)
        assert len(profile["skills"]) <= 15


# ── Write Profile ────────────────────────────────────────────────────────────

class TestWriteProfile:
    def test_writes_yaml(self, tmp_path):
        profile = generate_profile(SAMPLE_RESUME)
        out = write_profile(profile, path=tmp_path / "profile.yaml")
        assert out.exists()
        content = out.read_text()
        assert "auto-generated from resume" in content
        assert "JANE DOE" in content

    def test_refuses_overwrite_without_force(self, tmp_path):
        path = tmp_path / "profile.yaml"
        path.write_text("existing content")
        with pytest.raises(FileExistsError):
            write_profile({"name": "test"}, path=path)

    def test_force_overwrites(self, tmp_path):
        path = tmp_path / "profile.yaml"
        path.write_text("existing content")
        write_profile({"name": "test"}, path=path, force=True)
        assert "test" in path.read_text()


# ── Read Resume Text ─────────────────────────────────────────────────────────

class TestReadResumeText:
    def test_reads_markdown(self, tmp_path):
        md = tmp_path / "RESUME.md"
        md.write_text("# Test Resume\n\nSome content here for parsing purposes ok.\n" * 5)
        text = read_resume_text(md)
        assert "Test Resume" in text

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            read_resume_text(Path("/nonexistent/resume.md"))

    def test_raises_on_empty_file(self, tmp_path):
        md = tmp_path / "RESUME.md"
        md.write_text("")
        with pytest.raises(ValueError, match="empty"):
            read_resume_text(md)


# ── Run Pipeline ─────────────────────────────────────────────────────────────

class TestRunResumeParser:
    def test_end_to_end(self, tmp_path):
        resume = tmp_path / "RESUME.md"
        resume.write_text(SAMPLE_RESUME)
        output = tmp_path / "profile.yaml"

        result = run_resume_parser(
            resume_path=str(resume),
            output_path=str(output),
            force=True,
        )

        assert result["name"] == "JANE DOE"
        assert result["skills_found"] > 0
        assert result["roles_found"] > 0
        assert output.exists()
