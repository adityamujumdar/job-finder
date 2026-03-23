"""Claude LLM integration layer — optional semantic intelligence for JobHunter AI.

Provides structured Claude calls for tasks where regex/heuristics fall short:
  • Resume parsing: extract name, location, skills, roles from free-form text
  • Title matching: semantic job-title-to-role relevance scoring
  • Skill extraction: section-aware skill classification from job descriptions

Design principles:
  1. OPTIONAL — every function gracefully degrades if no API key is set
  2. CACHED — results are cached to avoid redundant API calls
  3. STRUCTURED — all prompts return JSON for deterministic downstream parsing
  4. COST-AWARE — only called for P1+P2 subset (~1,200 jobs), never 502K bulk

Usage:
  Set ANTHROPIC_API_KEY in environment or .env file.
  If unset, all functions return None and callers fall back to regex.

Cost model (Haiku pricing, ~$0.25/M input, ~$1.25/M output):
  • Resume parse: ~2K tokens → ~$0.001 per resume (one-time)
  • Title match:  ~500 tokens → ~$0.0003 per job × 1,200 = ~$0.36/run
  • Skill extract: ~1K tokens → ~$0.0005 per job × 1,200 = ~$0.60/run
  Total: ~$1/day for full pipeline with LLM enhancement
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

log = logging.getLogger(__name__)

# ── Client Management ─────────────────────────────────────────────────────────

_client = None
_available: bool | None = None

# Model selection: Haiku for speed+cost, Sonnet for quality
# Haiku: ~0.5s latency, $0.25/$1.25 per M tokens
# Sonnet: ~2s latency, $3/$15 per M tokens
MODEL = os.environ.get("JOBHUNTER_LLM_MODEL", "claude-3-haiku-20240307")
MAX_RETRIES = 2
RETRY_DELAY = 1.0  # seconds


def is_available() -> bool:
    """Check if Claude API is available (API key set and SDK importable)."""
    global _available, _client
    if _available is not None:
        return _available

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _available = False
        log.debug("LLM not available: ANTHROPIC_API_KEY not set")
        return False

    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        _available = True
        log.info("LLM available: using model %s", MODEL)
        return True
    except ImportError:
        _available = False
        log.debug("LLM not available: anthropic SDK not installed")
        return False
    except Exception as e:
        _available = False
        log.warning("LLM init failed: %s", e)
        return False


def call_claude(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> str | None:
    """Make a single Claude API call with retry logic.

    Args:
        prompt: User message content.
        system: Optional system prompt.
        max_tokens: Max response tokens (default 1024).
        temperature: Sampling temperature (0.0 = deterministic).

    Returns:
        Response text or None on failure. Never raises.
    """
    if not is_available():
        return None

    for attempt in range(MAX_RETRIES + 1):
        try:
            kwargs: dict[str, Any] = {
                "model": MODEL,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

            response = _client.messages.create(**kwargs)
            text = response.content[0].text
            return text

        except Exception as e:
            if attempt < MAX_RETRIES:
                log.debug("LLM call failed (attempt %d): %s", attempt + 1, e)
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                log.warning("LLM call failed after %d attempts: %s", MAX_RETRIES + 1, e)
                return None

    return None


def _parse_json_response(text: str | None) -> dict | None:
    """Extract JSON from Claude's response, handling markdown code blocks."""
    if not text:
        return None

    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```\s*$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        log.debug("Failed to parse LLM JSON response: %s", text[:200])
        return None


# ── Resume Parsing ────────────────────────────────────────────────────────────

RESUME_SYSTEM = """You are a precise resume parser. Extract structured data from resume text.
Return ONLY valid JSON, no markdown, no explanation. Be exact — do not infer data not present."""

RESUME_PROMPT = """Parse this resume and extract the following fields as JSON:

{{
  "name": "Full name (string)",
  "email": "Email address (string, empty if not found)",
  "location": "City, State/Province abbreviation (e.g., 'San Francisco, CA' or 'Toronto, ON')",
  "years_experience": integer (total years from earliest job to latest),
  "skills": ["list", "of", "technical", "skills", "mentioned"],
  "roles": ["list", "of", "job", "titles", "held"],
  "target_level": "entry|mid|senior|staff|principal (based on experience)"
}}

Rules:
- For skills: include programming languages, frameworks, tools, platforms, and methodologies
- For roles: extract actual job titles held, not descriptions
- For years_experience: calculate from the earliest start date to the most recent end date (or today if "Present")
- For location: use the most recent location mentioned, prefer "City, ST" format
- For target_level: 0-2 years=entry, 2-5=mid, 5-10=senior, 10-15=staff, 15+=principal

Resume text:
---
{resume_text}
---

JSON:"""


def parse_resume(text: str) -> dict | None:
    """Parse resume text using Claude for structured extraction.

    Returns dict with keys: name, email, location, years_experience,
    skills, roles, target_level. Returns None if LLM unavailable.
    """
    if not is_available():
        return None

    # Truncate very long resumes to save tokens (first 4K chars is plenty)
    truncated = text[:4000] if len(text) > 4000 else text
    prompt = RESUME_PROMPT.format(resume_text=truncated)

    response = call_claude(prompt, system=RESUME_SYSTEM, max_tokens=1024)
    result = _parse_json_response(response)

    if not result:
        log.warning("LLM resume parse returned invalid JSON")
        return None

    # Validate required fields
    required = {"name", "skills", "roles"}
    if not all(k in result for k in required):
        log.warning("LLM resume parse missing required fields: %s", required - set(result.keys()))
        return None

    # Normalize types
    result.setdefault("email", "")
    result.setdefault("location", "")
    result.setdefault("years_experience", 0)
    result.setdefault("target_level", "mid")
    if isinstance(result.get("years_experience"), str):
        try:
            result["years_experience"] = int(result["years_experience"])
        except ValueError:
            result["years_experience"] = 0

    return result


# ── Title Matching ────────────────────────────────────────────────────────────

TITLE_SYSTEM = """You are a job title relevance scorer. Score how relevant a job title is to a candidate's target roles.
Return ONLY valid JSON. Be precise and consistent."""

TITLE_PROMPT = """Score the relevance of this job title to the candidate's target roles.

Job title: "{job_title}"
Target roles: {target_roles}

Return JSON:
{{
  "score": float between 0.0 and 1.0,
  "reasoning": "one sentence explanation"
}}

Scoring guide:
- 1.0: Exact match or trivially equivalent (e.g., "Backend Engineer" matches "Software Engineer, Backend")
- 0.85-0.95: Same role family, different seniority or specialization
- 0.6-0.85: Related role, significant overlap in responsibilities
- 0.3-0.6: Tangentially related, some skill overlap
- 0.0-0.3: Different job family entirely

Important: Score based on actual job responsibility overlap, not just keyword matching.
"Data Engineer" and "Data Analyst" are related (~0.6) but distinct roles.
"Software Engineer - Data Platform" and "Data Engineer" are very close (~0.9).

JSON:"""


def classify_title_match(job_title: str, target_roles: list[str]) -> dict | None:
    """Score job title relevance to target roles using Claude.

    Returns {"score": float, "reasoning": str} or None if LLM unavailable.
    Score is 0.0-1.0, directly usable as title_match factor.
    """
    if not is_available() or not job_title or not target_roles:
        return None

    prompt = TITLE_PROMPT.format(
        job_title=job_title,
        target_roles=json.dumps(target_roles),
    )

    response = call_claude(prompt, system=TITLE_SYSTEM, max_tokens=256)
    result = _parse_json_response(response)

    if not result or "score" not in result:
        return None

    # Clamp score to valid range
    try:
        score = float(result["score"])
        result["score"] = max(0.0, min(1.0, score))
    except (ValueError, TypeError):
        return None

    return result


# ── Skill Extraction from Job Descriptions ────────────────────────────────────

SKILLS_SYSTEM = """You are a precise job description analyzer. Extract skill requirements and classify them.
Return ONLY valid JSON, no markdown, no explanation."""

SKILLS_PROMPT = """Analyze this job description and classify the candidate's skills.

Candidate's skills: {profile_skills}

Job description (truncated):
---
{jd_text}
---

Return JSON:
{{
  "required": ["skills from the candidate's list that are REQUIRED by this job"],
  "nice_to_have": ["skills from the candidate's list that are NICE-TO-HAVE/preferred"],
  "not_mentioned": ["skills from the candidate's list NOT mentioned in the job description"]
}}

Rules:
- ONLY use skills from the candidate's skill list — do not add new ones
- "Required" = explicitly listed under requirements, qualifications, must-have sections
- "Nice to have" = listed under preferred, bonus, nice-to-have sections, or mentioned casually
- If a skill appears in both required and nice sections, classify as required
- If the description doesn't clearly distinguish sections, classify mentioned skills as required

JSON:"""


def extract_jd_skills(
    jd_text: str, profile_skills: list[str]
) -> dict[str, list[str]] | None:
    """Extract and classify skills from a job description using Claude.

    Returns {"required": [...], "nice_to_have": [...]} or None if LLM unavailable.
    Only classifies skills from the profile_skills list (not arbitrary extraction).
    """
    if not is_available() or not jd_text or not profile_skills:
        return None

    # Truncate JD to save tokens (3K chars covers most descriptions)
    truncated = jd_text[:3000] if len(jd_text) > 3000 else jd_text
    prompt = SKILLS_PROMPT.format(
        profile_skills=json.dumps(profile_skills),
        jd_text=truncated,
    )

    response = call_claude(prompt, system=SKILLS_SYSTEM, max_tokens=512)
    result = _parse_json_response(response)

    if not result:
        return None

    # Validate and filter — only return skills that are in profile_skills
    profile_set = {s.lower() for s in profile_skills}
    required = [
        s for s in result.get("required", [])
        if s.lower() in profile_set
    ]
    nice = [
        s for s in result.get("nice_to_have", [])
        if s.lower() in profile_set
    ]

    return {"required": required, "nice_to_have": nice}


# ── Batch Helpers ─────────────────────────────────────────────────────────────

def batch_classify_titles(
    jobs: list[dict],
    target_roles: list[str],
    title_key: str = "title",
) -> dict[str, float]:
    """Batch-classify job titles for a list of jobs.

    Returns {job_url: llm_title_score} for jobs where LLM succeeded.
    Jobs where LLM fails are omitted (caller falls back to regex score).
    """
    if not is_available():
        return {}

    results = {}
    seen_titles: dict[str, float] = {}  # cache identical titles

    for job in jobs:
        title = job.get(title_key, "")
        url = job.get("url", "")
        if not title or not url:
            continue

        # Cache hit — same title already classified
        title_lower = title.lower().strip()
        if title_lower in seen_titles:
            results[url] = seen_titles[title_lower]
            continue

        result = classify_title_match(title, target_roles)
        if result:
            score = result["score"]
            results[url] = score
            seen_titles[title_lower] = score

    log.info(
        "LLM title classification: %d/%d jobs scored (%d unique titles)",
        len(results), len(jobs), len(seen_titles),
    )
    return results
