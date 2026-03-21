"""Job description enricher — fetches and parses descriptions for scored jobs.

Fetches full job descriptions from ATS APIs (Greenhouse, Lever, Ashby) and
optionally via gstack/browse for Workday. Extracts required/nice-to-have skills
and salary ranges using regex. Saves a sidecar file in data/enriched/DATE.json
keyed by job URL.

Data flow:
  data/scored/DATE.json (P1+P2 jobs)
        │
  enricher.py (async HTTP, concurrency=8)
        │
  ┌─────────────────────────────────────────────────────┐
  │  Greenhouse boards-api  → JSON content field        │
  │  Lever posting API      → JSON text field           │
  │  Ashby posting API      → JSON descriptionHtml      │
  │  Workday                → gstack/browse (fallback)  │
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
  404/410 → expired=True, no skills
  429     → backoff 2/4/8s, then unenriched=True
  timeout → unenriched=True
  empty   → unenriched=True
  no text → unenriched=True
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


def fetch_greenhouse(slug: str, job_id: str) -> str | None:
    """Fetch job description HTML from Greenhouse boards-api v1.

    Returns cleaned plain text or None on failure.
    """
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
    r = _http_get(api_url)
    if r is None or r.status_code == 404:
        return None  # expired or not found
    if r.status_code != 200:
        log.debug("Greenhouse %s/%s → %d", slug, job_id, r.status_code)
        return None
    try:
        data = r.json()
        content = data.get("content", "")
        return _html_to_text(content) if content else None
    except Exception as e:
        log.debug("Greenhouse JSON parse error for %s/%s: %s", slug, job_id, e)
        return None


def fetch_lever(slug: str, job_id: str) -> str | None:
    """Fetch job description from Lever posting API.

    Returns cleaned plain text or None on failure.
    """
    api_url = f"https://api.lever.co/v0/postings/{slug}/{job_id}"
    r = _http_get(api_url)
    if r is None or r.status_code == 404:
        return None
    if r.status_code != 200:
        return None
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
        return text if len(text) >= MIN_DESCRIPTION_CHARS else None
    except Exception as e:
        log.debug("Lever parse error for %s/%s: %s", slug, job_id, e)
        return None


def fetch_ashby(slug: str, job_id: str) -> str | None:
    """Fetch job description from Ashby posting API.

    Returns cleaned plain text or None on failure.
    """
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}/posting/{job_id}"
    r = _http_get(api_url)
    if r is None or r.status_code == 404:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        # Ashby returns descriptionHtml or descriptionPlain at top level
        if data.get("descriptionPlain"):
            return data["descriptionPlain"]
        if data.get("descriptionHtml"):
            return _html_to_text(data["descriptionHtml"])
    except Exception as e:
        log.debug("Ashby parse error for %s/%s: %s", slug, job_id, e)
    return None


def fetch_via_browse(url: str) -> str | None:
    """Fetch job page text via gstack/browse (used for Workday and unknown ATS).

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

def enrich_job(job: dict, profile: dict) -> dict[str, Any]:
    """Enrich a single job with description, skills, and salary.

    Tries ATS-specific APIs in order. Falls back to gstack/browse for Workday.
    Returns an enrichment dict suitable for storing in enriched/DATE.json.

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
                description_text = fetch_greenhouse(slug, job_id)
                if description_text is None:
                    # Check if it's actually a 404 (expired listing)
                    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
                    r = requests.get(api_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
                    if r.status_code in (404, 410):
                        expired = True

        elif ats == "lever":
            info = extract_lever_info(url)
            if info:
                slug, job_id = info
                description_text = fetch_lever(slug, job_id)

        elif ats == "ashby":
            info = extract_ashby_info(url)
            if info:
                slug, job_id = info
                description_text = fetch_ashby(slug, job_id)

        elif ats == "workday":
            # Workday has no clean JSON API — try gstack/browse if available
            description_text = fetch_via_browse(url)

        # Unknown ATS: try browse as best-effort
        elif ats == "unknown":
            description_text = fetch_via_browse(url)

    except Exception as e:
        log.warning("Unexpected error enriching %s: %s", url, e)

    if not description_text or len(description_text) < MIN_DESCRIPTION_CHARS:
        return {
            "url": url,
            "unenriched": True,
            "expired": expired,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    # Extract skills and salary
    profile_skills = profile.get("skills", [])
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

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        future_to_job = {
            pool.submit(enrich_job, job, profile): job
            for job in target_jobs
        }
        for i, future in enumerate(as_completed(future_to_job), 1):
            job = future_to_job[future]
            url = job.get("url", "")
            try:
                result = future.result()
                results[url] = result
                if result.get("unenriched"):
                    error += 1
                else:
                    success += 1
            except Exception as e:
                log.warning("Enrichment failed for %s: %s", url, e)
                results[url] = {"url": url, "unenriched": True, "error": str(e)}
                error += 1

            if i % 50 == 0:
                log.info("  enriched %d/%d (%.0f%%)", i, len(target_jobs), i/len(target_jobs)*100)

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
        "Enrichment complete: %d success, %d unenriched in %.1fs",
        success, error, elapsed
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
