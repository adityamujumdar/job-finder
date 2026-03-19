"""Vendored from github.com/Feashliaa/job-board-aggregator (MIT License)
Pinned SHA: d6f4af0bda51e9cf7feeffb24c8f857942cd73e6
Run scripts/update_vendor.sh to check for upstream changes.

MIT License — Copyright (c) 2026 Riley Dorrington

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Modifications from upstream:
  - Removed: save_results(), main(), argparse, OUTPUT_DIR, file I/O
  - Changed: load_companies() accepts list param instead of file path
  - Added: get_dedup_key() from merge_data.py
  - Added: get_composite_key() for fallback dedup
  - Added: fetch_company_jobs() dispatcher
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── Constants ──────────────────────────────────────────────────────────────────

RECRUITER_TERMS = [
    "recruit", "recruiting", "recruiter", "staffing", "staff", "talent",
    "talenthub", "talentgroup", "solutions", "consulting", "placement",
    "search", "resources", "agency",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:147.0) Gecko/20100101 Firefox/147.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
]

# Worker counts per platform
MAX_WORKERS = {
    "bamboohr": 10,
    "greenhouse": 30,
    "ashby": 30,
    "lever": 30,
    "workday": 30,
    "workable": 30,
}

# Map platform names to fetcher functions
PLATFORM_FETCHERS = {}  # Populated at module bottom


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_job_metadata():
    """Generate consistent metadata for each job."""
    return {
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "live",
    }


def is_recruiter_company(slug: str) -> bool:
    """Check if company slug contains recruiter/staffing terms."""
    slug_lower = slug.lower()
    return any(term in slug_lower for term in RECRUITER_TERMS)


def job_tier_classification(title: str) -> str:
    """Classify job tier using weighted keyword scoring.
    Returns: 'intern', 'entry', 'mid', or 'senior'.
    """
    title_lower = title.lower()
    score = 0

    keywords = {
        r"\b(?:chief|cto|ceo|cfo|vp|vice president|director)\b": 50,
        r"\b(?:principal|distinguished|fellow)\b": 40,
        r"\b(?:staff|lead|head of)\b": 30,
        r"\b(?:senior|sr\.?)\b": 20,
        r"\b(?:architect|manager)\b": 15,
        r"\b(?:iii|iv|v|vi)\b": 15,
        r"\blevel\s*[4-9]\b": 15,
        r"\bengr?\s*[4-6]\b": 15,
        r"\b(?:counsel|of\s*counsel)\b": 20,
        r"\b(?:attending|charge)\b": 20,
        r"\b(?:ii|2)\b": 5,
        r"\blevel\s*3\b": 5,
        r"\b(?:associate)\b": -10,
        r"\b(?:junior|jr\.?)\b": -20,
        r"\b(?:trainee|graduate|new\s*grad)\b": -25,
        r"\bentry[\s-]?level\b": -25,
        r"\b(?:i|1)\b(?!\s*-|\d)": -15,
        r"\b(?:paralegal|clerk)\b": -15,
        r"\b(?:resident|clinical\s*fellow)\b": -15,
        r"\b(?:aide|assistant)\b": -10,  # LOCAL PATCH: removed "tech" — matches legitimate SWE titles (Tech Lead, etc.)
        r"\bintern(?:ship)?\b": -100,
    }

    for pattern, weight in keywords.items():
        if re.search(pattern, title_lower):
            score += weight

    if score <= -50:
        return "intern"
    elif score <= -5:
        return "entry"
    elif score >= 15:
        return "senior"
    else:
        return "mid"


def clean_job_data(jobs: list[dict]) -> list[dict]:
    """Remove invalid/useless job entries."""
    cleaned = []
    skipped = {"no_title": 0, "no_url": 0, "no_company": 0}

    for job in jobs:
        title = (job.get("title") or "").strip().lower()
        url = job.get("url") or job.get("absolute_url")
        company = job.get("company") or job.get("company_slug")

        if not title or title in ("not specified", "n/a", "unknown", ""):
            skipped["no_title"] += 1
            continue
        if not url:
            skipped["no_url"] += 1
            continue
        if not company:
            skipped["no_company"] += 1
            continue

        cleaned.append(job)

    total_skipped = sum(skipped.values())
    if total_skipped > 0:
        print(f"  Cleaned: skipped {total_skipped:,} invalid jobs "
              f"(title:{skipped['no_title']}, url:{skipped['no_url']}, company:{skipped['no_company']})")

    return cleaned


# ── Dedup Keys ─────────────────────────────────────────────────────────────────

def get_dedup_key(job: dict) -> str:
    """Primary dedup key — URL-based, with Workday special handling.
    From JBA's merge_data.py.
    """
    url = job.get("url", "")
    if job.get("ats") == "Workday":
        match = re.search(r"/jobs/(\d+)", url)
        if match:
            company = job.get("company", "")
            return f"workday:{company}:{match.group(1)}"
    return url


def get_composite_key(job: dict) -> str:
    """Fallback dedup key — (ats, slug, job_id) composite.
    Catches duplicates when URLs differ but it's the same job.
    """
    ats = (job.get("ats") or "unknown").lower()
    slug = (job.get("company_slug") or job.get("company") or "unknown").lower()

    # Extract job ID from URL patterns
    url = job.get("url", "")
    job_id = ""

    if ats == "greenhouse":
        match = re.search(r"/jobs/(\d+)", url)
        if match:
            job_id = match.group(1)
    elif ats == "ashby":
        # URL: https://jobs.ashbyhq.com/{slug}/{uuid}
        match = re.search(r"ashbyhq\.com/[^/]+/([a-f0-9-]+)", url)
        if match:
            job_id = match.group(1)
    elif ats == "lever":
        # URL: https://jobs.lever.co/{slug}/{uuid}
        match = re.search(r"lever\.co/[^/]+/([a-f0-9-]+)", url)
        if match:
            job_id = match.group(1)
    elif ats == "workday":
        match = re.search(r"/jobs/(\d+)", url)
        if match:
            job_id = match.group(1)
    elif ats == "bamboohr":
        # URL: https://{slug}.bamboohr.com/careers/view/{id}
        match = re.search(r"/view/(\d+)", url)
        if match:
            job_id = match.group(1)
    elif ats == "workable":
        match = re.search(r"/jobs/(\w+)", url)
        if match:
            job_id = match.group(1)

    return f"{ats}:{slug}:{job_id}" if job_id else ""


# ── ATS Fetchers ───────────────────────────────────────────────────────────────

def fetch_company_jobs_greenhouse(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for a Greenhouse company."""
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        response = requests.get(url, timeout=30)

        if response.status_code == 200:
            data = response.json()
            jobs = data.get("jobs", [])
            if jobs:
                normalized = []
                for job in jobs:
                    normalized.append({
                        "company": slug,
                        "company_slug": slug,
                        "title": job.get("title"),
                        "location": job.get("location", {}).get("name", "Not specified"),
                        "url": job.get("absolute_url"),
                        "departments": [d.get("name") for d in job.get("departments", [])],
                        "id": job.get("id"),
                        "is_recruiter": is_recruiter_company(slug),
                        "ats": "Greenhouse",
                        "skill_level": job_tier_classification(job.get("title", "")),
                        **get_job_metadata(),
                    })
                return slug, normalized
    except Exception as e:
        print(f"  Error: Greenhouse/{slug}: {e}")
    return slug, []


def fetch_company_jobs_ashby(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for an Ashby company."""
    try:
        url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
        payload = {
            "operationName": "ApiJobBoardWithTeams",
            "variables": {"organizationHostedJobsPageName": slug},
            "query": ("query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) "
                      "{ jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: "
                      "$organizationHostedJobsPageName) { jobPostings { id title locationName } } }"),
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; JobFetcher/1.0)",
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            postings = ((data.get("data") or {}).get("jobBoard") or {}).get("jobPostings") or []
            if postings:
                normalized = []
                for job in postings:
                    normalized.append({
                        "company": slug,
                        "company_slug": slug,
                        "title": job.get("title", ""),
                        "location": (job.get("locationName") or "Not specified")[:50],
                        "url": f"https://jobs.ashbyhq.com/{slug}/{job.get('id')}",
                        "is_recruiter": is_recruiter_company(slug),
                        "ats": "Ashby",
                        "skill_level": job_tier_classification(job.get("title", "")),
                        **get_job_metadata(),
                    })
                return slug, normalized
    except Exception as e:
        print(f"  Error: Ashby/{slug}: {e}")
    return slug, []


def fetch_company_jobs_bamboohr(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for a BambooHR company."""
    url = f"https://{slug}.bamboohr.com/careers/list"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; ATSProbe/1.0)",
    }
    try:
        response = requests.get(url, timeout=30, headers=headers)
        if response.status_code == 200:
            if "application/json" not in response.headers.get("Content-Type", ""):
                return slug, []
            data = response.json()
            jobs = data.get("result", [])
            if jobs:
                normalized = []
                for job in jobs:
                    loc = job.get("location") or {}
                    if isinstance(loc, dict):
                        city = loc.get("city", "")
                        state = loc.get("state", "")
                        location = ", ".join(filter(None, [city, state])) or "Not specified"
                    else:
                        location = str(loc) if loc else "Not specified"
                    normalized.append({
                        "company": slug,
                        "company_slug": slug,
                        "title": job.get("jobOpeningName"),
                        "location": location[:50],
                        "url": f"https://{slug}.bamboohr.com/careers/view/{job.get('id')}",
                        "is_recruiter": is_recruiter_company(slug),
                        "ats": "BambooHR",
                        "skill_level": job_tier_classification(job.get("jobOpeningName", "")),
                        **get_job_metadata(),
                    })
                return slug, normalized
    except Exception as e:
        print(f"  Error: BambooHR/{slug}: {e}")
    return slug, []


def fetch_company_jobs_lever(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for a Lever company. Lever can be flaky — retry with longer timeout."""
    for attempt, timeout in [(1, 30), (2, 60)]:
        try:
            url = f"https://api.lever.co/v0/postings/{slug}"
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                jobs = response.json()
                if jobs:
                    normalized = []
                    for job in jobs:
                        categories = job.get("categories", {})
                        normalized.append({
                            "company": slug,
                            "company_slug": slug,
                            "title": job.get("text"),
                            "location": (categories.get("location") or "Not specified")[:50],
                            "url": job.get("hostedUrl"),
                            "is_recruiter": is_recruiter_company(slug),
                            "ats": "Lever",
                            "skill_level": job_tier_classification(job.get("text", "")),
                            **get_job_metadata(),
                        })
                    return slug, normalized
                return slug, []  # Empty but valid
        except requests.Timeout:
            if attempt == 1:
                print(f"  Lever/{slug}: timeout at {timeout}s, retrying with {timeout*2}s...")
                continue
            print(f"  Error: Lever/{slug}: timeout after {timeout}s (attempt {attempt})")
        except Exception as e:
            print(f"  Error: Lever/{slug}: {e}")
            break
    return slug, []


def fetch_company_jobs_workday(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for a Workday company. Handles pagination + anti-bot jitter."""
    try:
        parts = slug.split("|")
        if len(parts) != 3:
            return slug, []

        company, wd, site_id = parts
        wd_num = wd.replace("wd", "")

        base_url = f"https://{company}.wd{wd_num}.myworkdayjobs.com"
        api_url = f"{base_url}/wday/cxs/{company}/{site_id}/jobs"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": random.choice(USER_AGENTS),
            "Origin": base_url,
            "Referer": f"{base_url}/{site_id}",
        }

        normalized = []
        offset = 0
        limit = 20
        retries = 0
        max_retries = 2
        observed_total = None

        while True:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }

            response = requests.post(api_url, json=payload, headers=headers, timeout=30)

            if response.status_code != 200:
                if retries < max_retries:
                    retries += 1
                    time.sleep(random.uniform(2.0, 4.0))
                    continue
                break

            data = response.json()
            jobs = data.get("jobPostings", [])
            total = data.get("total", 0)

            # Detect silent blocking
            if observed_total is None:
                observed_total = total
            elif total != observed_total:
                break

            if not jobs:
                break

            for job in jobs:
                job_path = job.get("externalPath", "")
                normalized.append({
                    "company": company,
                    "company_slug": slug,
                    "title": job.get("title"),
                    "location": (job.get("locationsText") or "Not specified")[:50],
                    "url": f"{base_url}/{site_id}{job_path}",
                    "is_recruiter": is_recruiter_company(company),
                    "ats": "Workday",
                    "skill_level": job_tier_classification(job.get("title", "")),
                    **get_job_metadata(),
                })

            offset += limit
            if offset >= total:
                break

            time.sleep(random.uniform(0.8, 1.8))

        return slug, normalized
    except Exception as e:
        print(f"  Error: Workday/{slug}: {e}")
        return slug, []


def fetch_company_jobs_workable(slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs for a Workable company."""
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    headers = {
        "Content-Type": "application/json",
        "Referer": f"https://apply.workable.com/{slug}/",
        "Origin": "https://apply.workable.com",
        "User-Agent": random.choice(USER_AGENTS),
    }
    try:
        payload = {
            "query": "", "location": [], "department": [],
            "worktype": [], "remote": [],
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            jobs = data.get("results", [])
            normalized = []
            for job in jobs:
                loc_info = job.get("location") or {}
                location = ", ".join(filter(None, [
                    loc_info.get("city", ""),
                    loc_info.get("region", ""),
                    loc_info.get("country", ""),
                ])) or "Not specified"
                normalized.append({
                    "company": slug,
                    "company_slug": slug,
                    "title": job.get("title"),
                    "location": location[:50],
                    "url": f"https://apply.workable.com/{slug}/jobs/{job.get('shortcode')}",
                    "is_recruiter": is_recruiter_company(slug),
                    "ats": "Workable",
                    "skill_level": job_tier_classification(job.get("title", "")),
                    **get_job_metadata(),
                })
            return slug, normalized
    except Exception as e:
        print(f"  Error: Workable/{slug}: {e}")
    return slug, []


# ── Batch Fetcher ──────────────────────────────────────────────────────────────

def fetch_all_jobs(
    companies: list[str] | set[str],
    fetcher,
    platform: str = "ATS",
) -> tuple[dict[str, int], list[dict]]:
    """Fetch jobs from all companies in parallel.

    Returns:
        (active_companies dict {slug: count}, all_jobs list)
    """
    all_jobs = []
    active_companies = {}
    failed = 0

    platform_lower = platform.lower()
    max_workers = MAX_WORKERS.get(platform_lower, 30)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetcher, slug): slug for slug in companies}

        for i, future in enumerate(as_completed(futures), 1):
            try:
                slug, jobs = future.result()
                if jobs:
                    all_jobs.extend(jobs)
                    active_companies[slug] = len(jobs)
                else:
                    failed += 1
            except Exception:
                failed += 1

    return active_companies, all_jobs


# ── Dispatcher ─────────────────────────────────────────────────────────────────

PLATFORM_FETCHERS = {
    "greenhouse": fetch_company_jobs_greenhouse,
    "ashby": fetch_company_jobs_ashby,
    "bamboohr": fetch_company_jobs_bamboohr,
    "lever": fetch_company_jobs_lever,
    "workday": fetch_company_jobs_workday,
    "workable": fetch_company_jobs_workable,
}


def fetch_company_jobs(platform: str, slug: str) -> tuple[str, list[dict]]:
    """Dispatch to the right fetcher by platform name."""
    fetcher = PLATFORM_FETCHERS.get(platform.lower())
    if not fetcher:
        print(f"  Unknown platform: {platform}")
        return slug, []
    return fetcher(slug)
