"""Job description enricher — fetches and parses descriptions for scored jobs.

Fetches full job descriptions from ATS APIs (Greenhouse, Lever, Ashby) and
via Playwright headless browser or gstack/browse for Workday. Extracts
required/nice-to-have skills and salary ranges using regex. Saves a sidecar
file in data/enriched/DATE.json keyed by job URL.

Data flow:
  data/scored/DATE.json (P1+P2 jobs)
        │
  incremental skip (enriched within 7 days → skip)
        │
  ┌─────────────────────────────────────────────────────┐
  │  API jobs (concurrent, ThreadPoolExecutor×8):       │
  │    Greenhouse boards-api  → JSON content field      │
  │    Lever posting API      → JSON text field         │
  │    Ashby posting API      → JSON descriptionHtml    │
  │                                                     │
  │  Browser jobs (sequential, main thread):            │
  │    Workday/Unknown → Playwright headless (primary)  │
  │                    → gstack/browse (fallback)       │
  │  Note: Playwright sync API uses greenlets and       │
  │  CANNOT be called from threads — must run on the    │
  │  thread that started the playwright instance.       │
  └─────────────────────────────────────────────────────┘
        │
  HTML → BeautifulSoup plain text
        │
  regex skill extraction  (profile skills, word-boundary)
  regex salary extraction ($XXX,XXX, CAD XXXk patterns)
        │
  data/enriched/DATE.json
  { url → { skills_required, skills_nice, salary,
             skill_match_pct, missing_skills,
             expired, unenriched, fetched_at } }

Shadow paths:
  404/410          → expired=True, no skills (Greenhouse/Lever/Ashby)
  expired content  → expired=True, no skills (Workday "page doesn't exist" etc.)
  429              → backoff 2/4/8s, then unenriched=True
  timeout          → unenriched=True
  empty            → unenriched=True
  no text          → unenriched=True

Browser fallback chain (Workday/unknown ATS):
  1. Playwright headless (works in CI + local)
     → wait for content selector → login page detection
  2. gstack/browse (local only, requires manual install)
  3. Both fail → unenriched=True (graceful degradation)

Expired detection (two layers):
  Layer 1: HTTP status — 404/410 from API fetchers (Greenhouse/Lever/Ashby)
  Layer 2: Content — EXPIRED_MARKERS in short (<1000 char) page text
           Catches Workday SPA pages that return HTTP 200 for dead jobs.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from src.config import (
    load_profile, today, ensure_dirs,
    SCORED_DIR, ENRICHED_DIR,
)

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CONCURRENCY = 8          # parallel HTTP workers
REQUEST_TIMEOUT = 8      # seconds per request
RETRY_DELAYS = [2, 4, 8] # exponential backoff on 429
MIN_DESCRIPTION_CHARS = 100  # below this → unenriched (likely a redirect page)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobHunter/1.0; +https://github.com/adityamujumdar/job-finder)",
    "Accept": "application/json, text/html",
}

# Salary regex patterns — matches USD/CAD/GBP ranges in various formats
# Examples: "$180,000–$220,000" | "CAD 120k-150k" | "£80-100K" | "$180K - $220K"
SALARY_PATTERNS = [
    r'[\$£€][\d,]+[Kk]?\s*[-–—to]+\s*[\$£€]?[\d,]+[Kk]?',   # $180K–$220K
    r'(?:USD|CAD|GBP)\s*[\d,]+[Kk]?\s*[-–—to]+\s*[\d,]+[Kk]?',  # CAD 120k-150k
    r'[\d,]+[Kk]?\s*[-–—to]+\s*[\d,]+[Kk]?\s*(?:per year|annually|\/yr)',  # 180k-220k per year
]
SALARY_RE = re.compile('|'.join(SALARY_PATTERNS), re.IGNORECASE)


# ── ATS Detection ─────────────────────────────────────────────────────────────

def detect_ats(job: dict) -> str:
    """Detect ATS from job's ats field (normalized to lowercase)."""
    ats = (job.get("ats") or "").lower()
    if ats in ("greenhouse",):
        return "greenhouse"
    if ats in ("lever",):
        return "lever"
    if ats in ("ashby",):
        return "ashby"
    if ats in ("workday",):
        return "workday"
    if ats in ("bamboohr",):
        return "bamboohr"
    return "unknown"


def extract_greenhouse_info(url: str) -> tuple[str, str] | None:
    """Extract (company_slug, job_id) from a Greenhouse job URL.

    Handles multiple URL patterns:
      Standard:  https://boards.greenhouse.io/{slug}/jobs/{id}
                 https://job-boards.greenhouse.io/{slug}/jobs/{id}
      Hosted:    https://{company}.com/jobs/search?gh_jid={id}
                 https://{company}.com/careers?gh_jid={id}
                 https://{company}.com/...?gh_jid={id}
      API board: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}

    Returns (slug, job_id) or None if not parseable.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        path = parsed.path or ""
        query = parse_qs(parsed.query)

        # Standard Greenhouse boards URL
        if "greenhouse.io" in hostname:
            # boards.greenhouse.io/{slug}/jobs/{id}
            # job-boards.greenhouse.io/{slug}/jobs/{id}
            parts = [p for p in path.split("/") if p]
            if "jobs" in parts:
                job_idx = parts.index("jobs")
                if job_idx > 0 and job_idx + 1 < len(parts):
                    slug = parts[job_idx - 1]
                    job_id = parts[job_idx + 1].split("?")[0]
                    return (slug, job_id)

        # Hosted Greenhouse board: ?gh_jid=XXXXXX in query string
        if "gh_jid" in query:
            job_id = query["gh_jid"][0]
            # Try to infer slug from hostname subdomain or known mappings
            # e.g. stripe.com → "stripe", lever.co domains are different ATS
            slug = hostname.split(".")[0]
            if slug not in ("www", "jobs", "careers", "boards"):
                return (slug, job_id)
            # Fallback: return with slug as first path segment
            parts = [p for p in path.split("/") if p]
            if parts:
                return (parts[0], job_id)

    except Exception:
        pass
    return None


def extract_lever_info(url: str) -> tuple[str, str] | None:
    """Extract (company_slug, job_id) from a Lever posting URL.

    Patterns:
      https://jobs.lever.co/{slug}/{uuid}
      https://lever.co/{slug}/{uuid}
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if "lever.co" in hostname:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2:
                return (parts[0], parts[1].split("?")[0])
    except Exception:
        pass
    return None


def extract_ashby_info(url: str) -> tuple[str, str] | None:
    """Extract (company_slug, job_id) from an Ashby posting URL.

    Patterns:
      https://jobs.ashbyhq.com/{slug}/{uuid}
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if "ashbyhq.com" in hostname:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2:
                return (parts[0], parts[1].split("?")[0])
    except Exception:
        pass
    return None


# ── HTTP Fetchers ──────────────────────────────────────────────────────────────

def _http_get(url: str) -> requests.Response | None:
    """GET with retries on 429. Returns Response or None on unrecoverable error."""
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            if r.status_code == 429:
                log.debug("Rate limited on %s (attempt %d), backing off %ds", url, attempt, delay or 2)
                continue  # retry with next delay
            return r
        except requests.RequestException as e:
            log.debug("Request error for %s (attempt %d): %s", url, attempt, e)
            if attempt == len(RETRY_DELAYS):
                return None
    return None  # exhausted retries


def fetch_greenhouse(slug: str, job_id: str) -> tuple[str | None, bool]:
    """Fetch job description HTML from Greenhouse boards-api v1.

    Returns (cleaned_text, expired) tuple:
      - (text, False) on success
      - (None, True) if job is expired (404/410)
      - (None, False) on other failures
    """
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
    r = _http_get(api_url)
    if r is None:
        return (None, False)
    if r.status_code in (404, 410):
        return (None, True)  # expired listing
    if r.status_code != 200:
        log.debug("Greenhouse %s/%s → %d", slug, job_id, r.status_code)
        return (None, False)
    try:
        data = r.json()
        content = data.get("content", "")
        text = _html_to_text(content) if content else None
        return (text, False)
    except Exception as e:
        log.debug("Greenhouse JSON parse error for %s/%s: %s", slug, job_id, e)
        return (None, False)


def fetch_lever(slug: str, job_id: str) -> tuple[str | None, bool]:
    """Fetch job description from Lever posting API.

    Returns (cleaned_text, expired) tuple:
      - (text, False) on success
      - (None, True) if job is expired (404)
      - (None, False) on other failures
    """
    api_url = f"https://api.lever.co/v0/postings/{slug}/{job_id}"
    r = _http_get(api_url)
    if r is None:
        return (None, False)
    if r.status_code == 404:
        return (None, True)  # expired listing
    if r.status_code != 200:
        return (None, False)
    try:
        data = r.json()
        # Lever returns { lists: [{text, content: [{text}]}], description, ... }
        parts = []
        if data.get("descriptionPlain"):
            parts.append(data["descriptionPlain"])
        elif data.get("description"):
            parts.append(_html_to_text(data["description"]))
        for section in data.get("lists", []):
            parts.append(section.get("text", ""))
            for item in section.get("content", []):
                parts.append(item.get("text", ""))
        text = "\n".join(p for p in parts if p)
        return (text, False) if len(text) >= MIN_DESCRIPTION_CHARS else (None, False)
    except Exception as e:
        log.debug("Lever parse error for %s/%s: %s", slug, job_id, e)
        return (None, False)


def fetch_ashby(slug: str, job_id: str) -> tuple[str | None, bool]:
    """Fetch job description from Ashby posting API.

    Returns (cleaned_text, expired) tuple:
      - (text, False) on success
      - (None, True) if job is expired (404)
      - (None, False) on other failures
    """
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}/posting/{job_id}"
    r = _http_get(api_url)
    if r is None:
        return (None, False)
    if r.status_code == 404:
        return (None, True)  # expired listing
    if r.status_code != 200:
        return (None, False)
    try:
        data = r.json()
        # Ashby returns descriptionHtml or descriptionPlain at top level
        if data.get("descriptionPlain"):
            return (data["descriptionPlain"], False)
        if data.get("descriptionHtml"):
            return (_html_to_text(data["descriptionHtml"]), False)
    except Exception as e:
        log.debug("Ashby parse error for %s/%s: %s", slug, job_id, e)
    return (None, False)


def fetch_via_browse(url: str) -> str | None:
    """Fetch job page text via gstack/browse (local only, used as fallback).

    Returns plain text or None if gstack not installed or fetch fails.
    """
    import os
    browse_bin_path = os.path.expanduser("~/.claude/skills/gstack/browse/bin/find-browse")
    try:
        result = subprocess.run(
            [browse_bin_path],
            capture_output=True, text=True, timeout=5
        )
        browser = result.stdout.strip().split("\n")[0] if result.returncode == 0 else ""
        if not browser:
            return None

        # Navigate to URL
        subprocess.run([browser, "goto", url], capture_output=True, timeout=30)
        # Get page text
        text_result = subprocess.run(
            [browser, "text"], capture_output=True, text=True, timeout=15
        )
        text = text_result.stdout.strip()
        return text if len(text) >= MIN_DESCRIPTION_CHARS else None
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        log.debug("gstack browse failed for %s: %s", url, e)
        return None


# ── Playwright Headless Browser ───────────────────────────────────────────────

# Workday content selectors — tried in order, first match wins.
# Different Workday themes use different DOM structures.
WORKDAY_SELECTORS = [
    '[data-automation-id="jobPostingDescription"]',   # Standard Workday
    '[data-automation-id="jobPostingPage"]',           # Alternate layout
    '.css-1q2dra3',                                     # Workday CSS class
    '#mainContent',                                     # Generic main content
]

# Login page markers — if ANY of these appear in the page text,
# the page is a login/auth wall, not the job description.
LOGIN_MARKERS = ["sign in", "create account", "workdayloginform", "forgot password"]

# Expired/dead job page markers — phrases that indicate the job listing has been
# removed, filled, or is no longer accepting applications. Checked after successful
# text fetch (especially Workday, which returns HTTP 200 for dead jobs).
EXPIRED_MARKERS = [
    "job is no longer available",
    "job you are looking for no longer exists",
    "position has been filled",
    "job posting is no longer active",
    "position is no longer available",
    "requisition is no longer active",
    "no longer accepting applications",
    "position has been closed",
    "job has expired",
    "job has been removed",
    "this job is closed",
    "this role has been filled",
    "job no longer exists",
    # Workday SPA — renders "The page you are looking for doesn't exist."
    # when a job posting has been taken down (HTTP 200, JS-rendered).
    "page you are looking for doesn't exist",
    "page you are looking for does not exist",
]

# Max text length to consider for expired detection. Real job descriptions are
# typically 1000+ chars. Expired pages are short boilerplate (200-500 chars).
# This prevents false positives on long JDs that mention "position filled" in context.
EXPIRED_MAX_CHARS = 1000


def _is_login_page(text: str) -> bool:
    """Detect if page text is a Workday login page instead of a job description."""
    text_lower = text.lower()
    # Require at least 2 markers to avoid false positives on job descriptions
    # that mention "create account" in benefits text
    matches = sum(1 for marker in LOGIN_MARKERS if marker in text_lower)
    return matches >= 2


def _is_expired_page(text: str) -> bool:
    """Detect if fetched page text is an expired/dead job listing.

    Workday (and some other ATS platforms) return HTTP 200 for expired jobs
    with a short message like "The job is no longer available." This check
    catches those cases that HTTP status codes miss.

    Uses a dual gate: text must match an expired marker AND be shorter than
    EXPIRED_MAX_CHARS. This prevents false positives on real job descriptions
    that incidentally mention "position has been filled" in context.
    """
    if len(text) > EXPIRED_MAX_CHARS:
        return False
    text_lower = text.lower()
    return any(marker in text_lower for marker in EXPIRED_MARKERS)


def fetch_workday_playwright(url: str, browser: Any = None) -> str | None:
    """Fetch job description from a Workday page using Playwright headless browser.

    Uses a shared browser instance (passed from run_enricher) with a fresh
    context per call for thread safety. Tries multiple Workday DOM selectors.

    Args:
        url: Workday job posting URL
        browser: Playwright Browser instance (None = Playwright not available)

    Returns:
        Plain text description or None on failure. Never raises.
    """
    if browser is None:
        return None

    context = None
    try:
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            java_script_enabled=True,
        )
        page = context.new_page()

        # Navigate with generous timeout (Workday SPAs are slow)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")

        # Try each selector — Workday themes vary across companies
        text = None
        for selector in WORKDAY_SELECTORS:
            try:
                page.wait_for_selector(selector, timeout=10000)
                element = page.query_selector(selector)
                if element:
                    text = element.text_content()
                    if text and len(text.strip()) >= MIN_DESCRIPTION_CHARS:
                        text = text.strip()
                        break
            except Exception:
                continue  # try next selector

        # Fallback: wait for network idle and grab full page text
        if not text or len(text) < MIN_DESCRIPTION_CHARS:
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
                text = page.text_content("body")
                text = text.strip() if text else ""
            except Exception:
                pass

        if not text or len(text) < MIN_DESCRIPTION_CHARS:
            return None

        # Login page detection — Workday may redirect to auth wall
        if _is_login_page(text):
            log.debug("Login page detected for %s — marking as unenriched", url)
            return None

        return text

    except Exception as e:
        # Catches playwright.TimeoutError, playwright.Error, and any other failure.
        # No in-function retry — fetch_with_browser falls back to gstack/browse.
        log.debug("Playwright fetch failed for %s: %s", url, type(e).__name__)
        return None
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass


def fetch_with_browser(url: str, browser: Any = None) -> str | None:
    """Fetch page text using Playwright (primary) → gstack/browse (fallback).

    Unified browser fetch for Workday and unknown ATS platforms. Tries
    Playwright headless first (works in CI + local), falls back to gstack
    (local only, requires manual install).

    Args:
        url: Job posting URL
        browser: Playwright Browser instance (None = Playwright not available)

    Returns:
        Plain text or None if both methods fail.
    """
    # Try 1: Playwright headless (works everywhere)
    text = fetch_workday_playwright(url, browser)
    if text:
        return text

    # Try 2: gstack/browse (local only, requires manual install)
    text = fetch_via_browse(url)
    if text:
        return text

    return None


# ── Text Processing ────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """Convert HTML/escaped HTML to clean plain text."""
    # Handle HTML-entity-encoded content (Greenhouse returns double-encoded)
    import html as html_lib
    decoded = html_lib.unescape(html)
    soup = BeautifulSoup(decoded, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def extract_skills(text: str, profile_skills: list[str]) -> dict[str, list[str]]:
    """Extract required and nice-to-have skills from job description text.

    Strategy:
      1. Find sections labeled "required", "must have", "qualifications" → required
      2. Find sections labeled "nice", "preferred", "bonus", "plus" → nice
      3. Classify profile skills found in each section
      4. Skills in required section (or unlabeled) → required
         Skills only in nice section → nice_to_have

    Returns {"required": [...], "nice_to_have": [...]}
    """
    if not text or not profile_skills:
        return {"required": [], "nice_to_have": []}

    text_lower = text.lower()

    # Split text into sections by common heading patterns
    section_breaks = re.split(
        r'\n(?=(?:required|must.have|qualifications|what you.ll need|minimum|basic|'
        r'nice.to.have|preferred|bonus|plus|desired|ideal|what we.d love|'
        r'what we.re looking for|responsibilities|about you|skills)\b)',
        text, flags=re.IGNORECASE
    )

    required_text = ""
    nice_text = ""

    REQUIRED_MARKERS = {"required", "must", "qualifications", "minimum", "basic", "need"}
    NICE_MARKERS = {"nice", "preferred", "bonus", "plus", "desired", "ideal", "love"}

    for section in section_breaks:
        first_line = section.split("\n")[0].lower()
        is_nice = any(m in first_line for m in NICE_MARKERS)
        is_required = any(m in first_line for m in REQUIRED_MARKERS)
        if is_nice:
            nice_text += " " + section
        elif is_required:
            required_text += " " + section
        else:
            required_text += " " + section  # untagged text defaults to required

    required_lower = required_text.lower()
    nice_lower = nice_text.lower()

    required_skills = []
    nice_skills = []

    for skill in profile_skills:
        skill_lower = skill.lower()
        pattern = r'\b' + re.escape(skill_lower) + r'\b'
        in_required = bool(re.search(pattern, required_lower))
        in_nice = bool(re.search(pattern, nice_lower))

        if in_required:
            required_skills.append(skill)
        elif in_nice:
            nice_skills.append(skill)

    return {
        "required": required_skills,
        "nice_to_have": nice_skills,
    }


def extract_salary(text: str) -> str | None:
    """Extract salary range from job description text using regex.

    Returns a clean salary string or None if not found.
    Examples: "$180,000–$220,000" → "$180K–$220K" (normalized)
    """
    if not text:
        return None

    match = SALARY_RE.search(text)
    if not match:
        return None

    raw = match.group(0).strip()
    # Normalize: remove spaces around dashes, normalize K notation
    normalized = re.sub(r'\s*[-–—to]+\s*', '–', raw)
    normalized = re.sub(r',(\d{3})', r'K', normalized)  # $180,000 → $180K (approx)
    # Cap at 30 chars to avoid runaway matches
    return normalized[:30] if len(normalized) <= 30 else raw[:30]


def compute_skill_match_pct(required_skills: list[str], profile_skills: list[str]) -> int:
    """Compute % of required skills found in profile. Returns 0-100 int."""
    if not required_skills:
        return 0  # no required skills found — can't compute match
    profile_lower = {s.lower() for s in profile_skills}
    matched = sum(1 for s in required_skills if s.lower() in profile_lower)
    return round(matched / len(required_skills) * 100)


# ── Per-Job Enrichment ────────────────────────────────────────────────────────

def _extract_skills_with_llm(text: str, profile_skills: list[str]) -> dict[str, list[str]] | None:
    """Try LLM-based skill extraction from job description.

    Returns {"required": [...], "nice_to_have": [...]} or None if LLM unavailable.
    Provides section-aware classification that regex struggles with (e.g., skills
    mentioned in "About Us" vs "Requirements" vs "Nice to Have" sections).
    """
    try:
        from src.llm import extract_jd_skills
        return extract_jd_skills(text, profile_skills)
    except ImportError:
        return None
    except Exception as e:
        log.debug("LLM skill extraction failed: %s", e)
        return None


def enrich_job(job: dict, profile: dict, browser: Any = None) -> dict[str, Any]:
    """Enrich a single job with description, skills, and salary.

    Tries ATS-specific APIs in order. For Workday/unknown ATS, uses
    fetch_with_browser() which tries Playwright → gstack/browse.
    Returns an enrichment dict suitable for storing in enriched/DATE.json.

    Args:
        job: Scored job dict with url, ats, etc.
        profile: Loaded user profile.
        browser: Playwright Browser instance (None = Playwright not available).

    All failures return a safe partial result — never raises.
    """
    url = job.get("url", "")
    ats = detect_ats(job)
    description_text: str | None = None
    expired = False

    try:
        if ats == "greenhouse":
            info = extract_greenhouse_info(url)
            if info:
                slug, job_id = info
                description_text, expired = fetch_greenhouse(slug, job_id)

        elif ats == "lever":
            info = extract_lever_info(url)
            if info:
                slug, job_id = info
                description_text, expired = fetch_lever(slug, job_id)

        elif ats == "ashby":
            info = extract_ashby_info(url)
            if info:
                slug, job_id = info
                description_text, expired = fetch_ashby(slug, job_id)

        elif ats in ("workday", "unknown"):
            # Workday has no clean JSON API, unknown ATS is best-effort.
            # fetch_with_browser tries Playwright → gstack/browse.
            description_text = fetch_with_browser(url, browser)

    except Exception as e:
        log.warning("Unexpected error enriching %s: %s", url, e)

    # Content-based expired detection — catches Workday (and other ATS) pages
    # that return HTTP 200 with "The job is no longer available" text.
    # Must run BEFORE the length gate and skill extraction to catch short
    # expired boilerplate that would otherwise be marked as unenriched.
    if description_text and not expired and _is_expired_page(description_text):
        log.debug("Expired page content detected for %s", url)
        return {
            "url": url,
            "expired": True,
            "unenriched": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    if not description_text or len(description_text) < MIN_DESCRIPTION_CHARS:
        return {
            "url": url,
            "unenriched": True,
            "expired": expired,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    # Extract skills and salary — LLM-first with regex fallback
    profile_skills = profile.get("skills", [])
    skill_result = _extract_skills_with_llm(description_text, profile_skills)
    if skill_result is None:
        skill_result = extract_skills(description_text, profile_skills)
    salary = extract_salary(description_text)
    required = skill_result["required"]
    nice = skill_result["nice_to_have"]

    skill_match_pct = compute_skill_match_pct(required, profile_skills) if required else None
    missing = [s for s in required if s.lower() not in {p.lower() for p in profile_skills}]

    return {
        "url": url,
        "skills_required": required,
        "skills_nice": nice,
        "salary": salary,
        "skill_match_pct": skill_match_pct,
        "missing_skills": missing,
        "expired": expired,
        "unenriched": False,
        "description_chars": len(description_text),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_enricher(date: str | None = None, limit: int | None = None) -> dict:
    """Fetch descriptions and extract skills for all P1+P2 scored jobs.

    Args:
        date: Date to enrich (YYYY-MM-DD). Defaults to today.
        limit: Max jobs to enrich (for testing). None = all P1+P2.

    Returns:
        Summary dict with counts and output path.
    """
    ensure_dirs()
    date_str = date or today()
    scored_path = SCORED_DIR / f"{date_str}.json"
    output_path = ENRICHED_DIR / f"{date_str}.json"

    if not scored_path.exists():
        log.error("No scored data for %s", date_str)
        return {"error": f"No scored data for {date_str}"}

    profile = load_profile()

    with open(scored_path) as f:
        all_jobs = json.load(f)

    # Select P1+P2 jobs, sorted by score (highest first)
    target_jobs = [j for j in all_jobs if j.get("_priority") in ("P1", "P2")]
    target_jobs.sort(key=lambda j: j.get("_score", 0), reverse=True)
    if limit:
        target_jobs = target_jobs[:limit]

    log.info("Enriching %d P1+P2 jobs (concurrency=%d)...", len(target_jobs), CONCURRENCY)
    t0 = time.time()

    # Load existing enriched data (for incremental re-enrichment)
    existing: dict[str, Any] = {}
    if output_path.exists():
        try:
            with open(output_path) as f:
                existing = json.load(f)
        except Exception:
            pass

    results: dict[str, Any] = dict(existing)  # preserve previously enriched jobs
    success = error = skipped = 0

    # Incremental skip: don't re-fetch jobs already successfully enriched
    # within SKIP_IF_ENRICHED_WITHIN_DAYS. Saves ~8 min/day of HTTP calls.
    SKIP_IF_ENRICHED_WITHIN_DAYS = 7
    skip_cutoff = datetime.now(timezone.utc).timestamp() - (SKIP_IF_ENRICHED_WITHIN_DAYS * 86400)

    jobs_to_enrich = []
    for job in target_jobs:
        url = job.get("url", "")
        prev = existing.get(url)
        if prev and not prev.get("unenriched") and prev.get("fetched_at"):
            try:
                fetched_ts = datetime.fromisoformat(prev["fetched_at"]).timestamp()
                if fetched_ts > skip_cutoff:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                pass  # malformed timestamp — re-enrich
        jobs_to_enrich.append(job)

    log.info("Skipping %d already-enriched jobs (within %d days)", skipped, SKIP_IF_ENRICHED_WITHIN_DAYS)

    # Split jobs into two groups:
    #   1. API jobs (Greenhouse/Lever/Ashby) → thread pool (concurrent HTTP)
    #   2. Browser jobs (Workday/unknown) → sequential on main thread (Playwright
    #      sync API uses greenlets and CANNOT be called from multiple threads)
    #
    # Pipeline:
    #   jobs_to_enrich
    #     ├── api_jobs ──────→ ThreadPoolExecutor(8) ──→ results
    #     └── browser_jobs ──→ sequential + Playwright ──→ results
    #
    api_jobs = []
    browser_jobs = []
    for job in jobs_to_enrich:
        ats = detect_ats(job)
        if ats in ("greenhouse", "lever", "ashby", "bamboohr"):
            api_jobs.append(job)
        else:
            browser_jobs.append(job)

    log.info("Enriching %d API jobs (concurrent) + %d browser jobs (sequential)",
             len(api_jobs), len(browser_jobs))

    def _record_result(job: dict, result: dict) -> None:
        """Record enrichment result and update counters."""
        nonlocal success, error
        url = job.get("url", "")
        results[url] = result
        if result.get("unenriched"):
            error += 1
        else:
            success += 1

    # Phase 1: API jobs via thread pool (no browser needed)
    if api_jobs:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            future_to_job = {
                pool.submit(enrich_job, job, profile, None): job
                for job in api_jobs
            }
            for i, future in enumerate(as_completed(future_to_job), 1):
                job = future_to_job[future]
                try:
                    _record_result(job, future.result())
                except Exception as e:
                    url = job.get("url", "")
                    log.warning("Enrichment failed for %s: %s", url, e)
                    results[url] = {"url": url, "unenriched": True, "error": str(e)}
                    error += 1

                if i % 50 == 0:
                    log.info("  api enriched %d/%d", i, len(api_jobs))

    # Phase 2: Browser jobs sequentially with Playwright on main thread
    # Playwright sync API uses greenlets — must stay on the thread that started it.
    pw_instance = None
    browser = None
    if browser_jobs:
        try:
            from playwright.sync_api import sync_playwright
            pw_instance = sync_playwright().start()
            browser = pw_instance.chromium.launch(headless=True)
            log.info("Playwright browser launched for %d browser jobs", len(browser_jobs))
        except ImportError:
            log.info("Playwright not installed — using gstack/browse only for Workday")
        except Exception as e:
            log.warning("Playwright launch failed (%s) — using gstack/browse only", e)

    try:
        for i, job in enumerate(browser_jobs, 1):
            try:
                result = enrich_job(job, profile, browser)
                _record_result(job, result)
            except Exception as e:
                url = job.get("url", "")
                log.warning("Enrichment failed for %s: %s", url, e)
                results[url] = {"url": url, "unenriched": True, "error": str(e)}
                error += 1

            if i % 20 == 0:
                log.info("  browser enriched %d/%d", i, len(browser_jobs))
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw_instance:
            try:
                pw_instance.stop()
            except Exception:
                pass

    elapsed = time.time() - t0

    with open(output_path, "w") as f:
        json.dump(results, f, separators=(",", ":"))

    summary = {
        "date": date_str,
        "total_attempted": len(target_jobs),
        "success": success,
        "unenriched": error,
        "skipped": skipped,
        "output_path": str(output_path),
        "elapsed_seconds": round(elapsed, 1),
    }

    log.info(
        "Enrichment complete: %d success, %d unenriched, %d skipped in %.1fs",
        success, error, skipped, elapsed
    )

    return summary


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="JobHunter enricher — fetch job descriptions")
    parser.add_argument("--date", type=str, default=None, help="Date to enrich (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to enrich (testing)")
    args = parser.parse_args()

    result = run_enricher(date=args.date, limit=args.limit)
    print(f"\n{json.dumps(result, indent=2)}")
