"""Unit tests for src/llm.py — Claude LLM integration layer.

Tests are fully isolated — no real API calls. All Claude calls are mocked.
Tests verify:
  1. Graceful degradation when no API key / SDK
  2. JSON parsing from various response formats
  3. Resume parsing prompt construction and result validation
  4. Title matching with score clamping
  5. Skill extraction with profile filtering
  6. Batch title classification with caching
  7. Retry logic on transient failures
"""

from __future__ import annotations

import json
import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

# Reset module-level state before each test
import src.llm as llm_module


@pytest.fixture(autouse=True)
def reset_llm_state():
    """Reset module-level singleton state between tests."""
    llm_module._client = None
    llm_module._available = None
    yield
    llm_module._client = None
    llm_module._available = None


# ── is_available() ────────────────────────────────────────────────────────────


class TestIsAvailable:
    def test_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert llm_module.is_available() is False

    def test_empty_api_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            assert llm_module.is_available() is False

    def test_valid_api_key(self):
        # Create a mock anthropic module for CI where it's not installed
        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test123"}):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                assert llm_module.is_available() is True

    def test_anthropic_import_error(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test123"}):
            with patch.dict("sys.modules", {"anthropic": None}):
                llm_module._available = None
                # ImportError path
                with patch("builtins.__import__", side_effect=ImportError("no anthropic")):
                    assert llm_module.is_available() is False

    def test_caches_result(self):
        """Second call returns cached value without re-checking."""
        llm_module._available = True
        assert llm_module.is_available() is True


# ── _parse_json_response() ───────────────────────────────────────────────────


class TestParseJsonResponse:
    def test_plain_json(self):
        result = llm_module._parse_json_response('{"name": "Alice", "score": 0.9}')
        assert result == {"name": "Alice", "score": 0.9}

    def test_markdown_code_block(self):
        text = '```json\n{"name": "Bob"}\n```'
        result = llm_module._parse_json_response(text)
        assert result == {"name": "Bob"}

    def test_code_block_no_language(self):
        text = '```\n{"x": 1}\n```'
        result = llm_module._parse_json_response(text)
        assert result == {"x": 1}

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"score": 0.75, "reasoning": "good match"} done.'
        result = llm_module._parse_json_response(text)
        assert result["score"] == 0.75

    def test_none_input(self):
        assert llm_module._parse_json_response(None) is None

    def test_empty_string(self):
        assert llm_module._parse_json_response("") is None

    def test_invalid_json(self):
        assert llm_module._parse_json_response("not json at all") is None


# ── call_claude() ─────────────────────────────────────────────────────────────


class TestCallClaude:
    def test_returns_none_when_unavailable(self):
        llm_module._available = False
        assert llm_module.call_claude("hello") is None

    def test_successful_call(self):
        llm_module._available = True
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="response text")]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.call_claude("test prompt", system="sys")
        assert result == "response text"
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "sys"
        assert call_kwargs["temperature"] == 0.0

    def test_retry_on_failure(self):
        llm_module._available = True
        mock_client = MagicMock()
        # First call fails, second succeeds
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_client.messages.create.side_effect = [
            Exception("rate limit"),
            mock_response,
        ]
        llm_module._client = mock_client

        with patch("time.sleep"):  # skip actual delay
            result = llm_module.call_claude("test")
        assert result == "ok"
        assert mock_client.messages.create.call_count == 2

    def test_all_retries_fail(self):
        llm_module._available = True
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("persistent error")
        llm_module._client = mock_client

        with patch("time.sleep"):
            result = llm_module.call_claude("test")
        assert result is None
        assert mock_client.messages.create.call_count == llm_module.MAX_RETRIES + 1


# ── parse_resume() ───────────────────────────────────────────────────────────


class TestParseResume:
    def test_returns_none_when_unavailable(self):
        llm_module._available = False
        assert llm_module.parse_resume("resume text") is None

    def test_successful_parse(self):
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "name": "Jane Doe",
            "email": "jane@example.com",
            "location": "San Francisco, CA",
            "years_experience": 8,
            "skills": ["Python", "AWS", "Kubernetes"],
            "roles": ["Senior Software Engineer", "Backend Engineer"],
            "target_level": "senior",
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.parse_resume("# Jane Doe\nSenior SWE...")
        assert result["name"] == "Jane Doe"
        assert result["years_experience"] == 8
        assert "Python" in result["skills"]
        assert len(result["roles"]) == 2

    def test_missing_required_fields(self):
        llm_module._available = True
        mock_client = MagicMock()
        # Missing "skills" field
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"name": "Bob"}')]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.parse_resume("some resume")
        assert result is None  # validation fails

    def test_string_years_normalized_to_int(self):
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "name": "X", "skills": ["Go"], "roles": ["SWE"],
            "years_experience": "5",
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.parse_resume("resume")
        assert result["years_experience"] == 5

    def test_truncates_long_resumes(self):
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "name": "X", "skills": ["Go"], "roles": ["SWE"],
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        long_resume = "A" * 10000
        llm_module.parse_resume(long_resume)

        # Verify the prompt was truncated
        call_args = mock_client.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        # The resume portion should be at most 4000 chars
        assert "A" * 4001 not in prompt_text


# ── classify_title_match() ───────────────────────────────────────────────────


class TestClassifyTitleMatch:
    def test_returns_none_when_unavailable(self):
        llm_module._available = False
        assert llm_module.classify_title_match("SWE", ["SWE"]) is None

    def test_returns_none_for_empty_title(self):
        llm_module._available = True
        assert llm_module.classify_title_match("", ["SWE"]) is None

    def test_returns_none_for_empty_roles(self):
        llm_module._available = True
        assert llm_module.classify_title_match("SWE", []) is None

    def test_successful_classification(self):
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "score": 0.92,
            "reasoning": "Strong match - same role family",
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.classify_title_match(
            "Senior Backend Engineer",
            ["Software Engineer", "Backend Engineer"],
        )
        assert result["score"] == 0.92
        assert "reasoning" in result

    def test_score_clamped_to_valid_range(self):
        llm_module._available = True
        mock_client = MagicMock()
        # LLM returns out-of-range score
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"score": 1.5, "reasoning": "oops"}')]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.classify_title_match("SWE", ["SWE"])
        assert result["score"] == 1.0  # clamped

    def test_negative_score_clamped(self):
        llm_module._available = True
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"score": -0.5, "reasoning": "bad"}')]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.classify_title_match("SWE", ["SWE"])
        assert result["score"] == 0.0


# ── extract_jd_skills() ──────────────────────────────────────────────────────


class TestExtractJdSkills:
    def test_returns_none_when_unavailable(self):
        llm_module._available = False
        assert llm_module.extract_jd_skills("jd text", ["Python"]) is None

    def test_returns_none_for_empty_inputs(self):
        llm_module._available = True
        assert llm_module.extract_jd_skills("", ["Python"]) is None
        assert llm_module.extract_jd_skills("jd text", []) is None

    def test_successful_extraction(self):
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "required": ["Python", "AWS"],
            "nice_to_have": ["Kubernetes"],
            "not_mentioned": ["Go"],
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.extract_jd_skills(
            "Requirements: Python, AWS. Nice to have: Kubernetes",
            ["Python", "AWS", "Kubernetes", "Go"],
        )
        assert result["required"] == ["Python", "AWS"]
        assert result["nice_to_have"] == ["Kubernetes"]

    def test_filters_skills_not_in_profile(self):
        """LLM might hallucinate skills not in the profile — filter them out."""
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({
            "required": ["Python", "Rust"],  # Rust not in profile
            "nice_to_have": ["TypeScript"],   # TypeScript not in profile
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        result = llm_module.extract_jd_skills(
            "Requires Python, Rust, TypeScript",
            ["Python", "AWS"],  # only Python and AWS in profile
        )
        assert result["required"] == ["Python"]
        assert result["nice_to_have"] == []


# ── batch_classify_titles() ──────────────────────────────────────────────────


class TestBatchClassifyTitles:
    def test_returns_empty_when_unavailable(self):
        llm_module._available = False
        assert llm_module.batch_classify_titles([], ["SWE"]) == {}

    def test_caches_identical_titles(self):
        """Same title string should only make one API call."""
        llm_module._available = True
        mock_client = MagicMock()
        response_json = json.dumps({"score": 0.85, "reasoning": "match"})
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        jobs = [
            {"title": "Software Engineer", "url": "https://a.com/1"},
            {"title": "Software Engineer", "url": "https://b.com/2"},
            {"title": "software engineer", "url": "https://c.com/3"},  # same after lower
        ]

        results = llm_module.batch_classify_titles(jobs, ["SWE"])
        assert len(results) == 3  # all three get scores
        # But only 1 API call (cached)
        assert mock_client.messages.create.call_count == 1

    def test_skips_empty_titles(self):
        llm_module._available = True
        mock_client = MagicMock()
        llm_module._client = mock_client

        jobs = [
            {"title": "", "url": "https://a.com/1"},
            {"title": "SWE", "url": ""},
        ]
        results = llm_module.batch_classify_titles(jobs, ["SWE"])
        assert len(results) == 0
        assert mock_client.messages.create.call_count == 0

    def test_handles_llm_failure_gracefully(self):
        """If LLM fails for a title, that job is omitted from results."""
        llm_module._available = True
        mock_client = MagicMock()
        # Return invalid JSON
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json")]
        mock_client.messages.create.return_value = mock_response
        llm_module._client = mock_client

        with patch("time.sleep"):
            jobs = [{"title": "SWE", "url": "https://a.com/1"}]
            results = llm_module.batch_classify_titles(jobs, ["SWE"])
        assert len(results) == 0  # failed, omitted


# ── Integration: resume_parser uses LLM ──────────────────────────────────────


class TestResumeParserLLMIntegration:
    def test_generate_profile_uses_llm_when_available(self):
        """generate_profile should use LLM extraction when available."""
        from src.resume_parser import generate_profile

        mock_llm_result = {
            "name": "LLM Name",
            "email": "llm@test.com",
            "location": "New York, NY",
            "years_experience": 10,
            "skills": ["Python", "Go", "Kubernetes", "AWS"],
            "roles": ["Staff Engineer", "Backend Engineer"],
            "target_level": "staff",
        }

        with patch("src.resume_parser._try_llm_extraction", return_value=mock_llm_result):
            profile = generate_profile("# Some Resume\nSome content here with enough text")
            assert profile["name"] == "LLM Name"
            assert profile["location"] == "New York, NY"
            assert profile["years_experience"] == 10

    def test_generate_profile_falls_back_to_regex(self):
        """generate_profile should fall back to regex when LLM unavailable."""
        from src.resume_parser import generate_profile

        with patch("src.resume_parser._try_llm_extraction", return_value=None):
            profile = generate_profile(
                "# John Smith\njohn@test.com | San Francisco, CA\n"
                "## Experience\n### Senior Software Engineer\n"
                "May 2020 – Present\n"
                "Skills: Python, AWS, Docker"
            )
            assert profile["name"] == "John Smith"
            assert "Python" in profile["skills"]


# ── Integration: enricher uses LLM ──────────────────────────────────────────


class TestEnricherLLMIntegration:
    def test_enrich_job_uses_llm_skills_when_available(self):
        """enrich_job should use LLM skill extraction when available."""
        from src.enricher import enrich_job

        mock_skills = {"required": ["Python", "AWS"], "nice_to_have": ["Go"]}

        profile = {"skills": ["Python", "AWS", "Go"]}
        job = {"url": "https://example.com/job/1", "ats": "greenhouse"}

        with patch("src.enricher.detect_ats", return_value="greenhouse"), \
             patch("src.enricher.extract_greenhouse_info", return_value=("company", "123")), \
             patch("src.enricher.fetch_greenhouse", return_value=("A long job description that meets the minimum character requirement " * 5, False)), \
             patch("src.enricher._extract_skills_with_llm", return_value=mock_skills), \
             patch("src.enricher.extract_salary", return_value=None):
            result = enrich_job(job, profile)
            assert result["skills_required"] == ["Python", "AWS"]
            assert result["skills_nice"] == ["Go"]
            assert result["unenriched"] is False

    def test_enrich_job_falls_back_to_regex_skills(self):
        """enrich_job should fall back to regex when LLM returns None."""
        from src.enricher import enrich_job

        profile = {"skills": ["Python", "AWS"]}
        job = {"url": "https://example.com/job/1"}

        # Description must be long enough and have skills as standalone words
        desc = (
            "Required qualifications:\n"
            "- Strong experience with Python programming\n"
            "- Experience with AWS cloud services\n"
            "About the role: This is a great opportunity. " * 10
        )

        with patch("src.enricher.detect_ats", return_value="greenhouse"), \
             patch("src.enricher.extract_greenhouse_info", return_value=("co", "1")), \
             patch("src.enricher.fetch_greenhouse", return_value=(desc, False)), \
             patch("src.enricher._extract_skills_with_llm", return_value=None), \
             patch("src.enricher.extract_salary", return_value=None):
            result = enrich_job(job, profile)
            assert result["unenriched"] is False
            # Regex should still find Python and AWS
            assert "Python" in result["skills_required"]
