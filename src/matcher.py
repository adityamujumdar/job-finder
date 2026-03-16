"""Job-level scoring and ranking engine.

Scores each job against the user's profile, classifies into priority tiers.
Score = weighted sum of: title_match, location_match, level_match,
        keyword_boost, company_preference, recency.
"""

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import (
    load_profile, profile_hash, today, ensure_dirs,
    JOBS_DIR, SCORED_DIR, WEIGHTS, PRIORITY_TIERS, PHOENIX_METRO, STALE_DAYS,
    COMPANY_BLOCKLIST,
)

log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Titles containing these words are a DIFFERENT job family — penalize hard
SWE_FAMILY_WORDS = {
    "software", "backend", "frontend", "fullstack", "full-stack", "devops",
    "sre", "ios", "android", "mobile", "web", "react", "node", "java",
    "ruby", "golang", "rust", "php", "net", "dotnet", "embedded",
    "backline", "infrastructure", "platform", "reliability", "security",
    "network", "systems", "cloud", "kubernetes", "ml",
}
IRRELEVANT_WORDS = {
    "center", "controls", "mechanical", "electrical", "civil", "chemical",
    "facilities", "hvac", "nurse", "nursing", "physician", "clinical",
    "teacher", "teaching", "sales", "recruiter", "recruiting", "legal",
    "counsel", "attorney", "janitor", "custodian", "driver", "delivery",
    "warehouse", "forklift", "cashier", "barista", "cook", "chef",
}

# BI abbreviation patterns
BI_PATTERNS = [
    r'\bbi\b',  # standalone "BI"
    r'\bbi[-/]',  # "BI-Developer", "BI/Analyst"
]


# ── Scoring Functions ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase word set, stripping punctuation."""
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def _normalize_title(title: str) -> str:
    """Normalize title for matching: lowercase, strip prefixes, clean punctuation."""
    t = title.lower().strip()
    # Remove common prefixes/suffixes that don't change the role
    t = re.sub(r'^(sr\.?|senior|junior|jr\.?|lead|staff|principal|head of|director of|vp of|manager of)\s+', '', t)
    # Normalize separators
    t = re.sub(r'\s*[-–—/,|:]\s*', ' - ', t)
    return t


def _phrase_in_title(role: str, title: str) -> bool:
    """Check if the role phrase appears as contiguous words in the title.

    Allows common title prefixes (Senior, Sr., Lead, Staff, II, III) between words
    but NOT unrelated words like "Center", "Controls", "Software".

    Examples:
      "Data Engineer" in "Senior Data Engineer" → True
      "Data Engineer" in "Data Engineer II" → True
      "Data Engineer" in "Data Center Controls Engineer" → False
      "BI Analyst" in "Senior BI Analyst - Reporting" → True
    """
    role_lower = role.lower().strip()
    title_lower = title.lower().strip()

    # Direct substring check first (fastest path)
    if role_lower in title_lower:
        return True

    # Check with BI expansion: "BI" → also try "Business Intelligence"
    if re.search(r'\bbi\b', role_lower):
        expanded = re.sub(r'\bbi\b', 'business intelligence', role_lower)
        if expanded in title_lower:
            return True

    # Check if title contains "BI" when role says "Business Intelligence"
    if 'business intelligence' in role_lower:
        bi_role = re.sub(r'business intelligence', 'bi', role_lower)
        if re.search(r'\b' + re.escape(bi_role) + r'\b', title_lower):
            return True

    return False


def score_title_match(job_title: str, profile: dict) -> float:
    """Score job title vs profile target roles using phrase matching.

    Strategy (in priority order):
      1. Exact phrase match: role appears as contiguous substring → 0.90-1.0
      2. BI/abbreviation expansion: "BI" ↔ "Business Intelligence" → 0.90-1.0
      3. Guarded Jaccard: token overlap BUT only if no SWE/irrelevant family words → 0.0-0.7

    Returns best match across all target roles.
    """
    if not job_title:
        return 0.0

    title_lower = job_title.lower().strip()
    title_tokens = _tokenize(job_title)
    if not title_tokens:
        return 0.0

    # Check for negative signals — SWE family or irrelevant job families
    has_swe_words = bool(title_tokens & SWE_FAMILY_WORDS)
    has_irrelevant = bool(title_tokens & IRRELEVANT_WORDS)

    # Check if title starts with a SWE role (e.g., "Software Engineer ... Data Engineering")
    title_starts_swe = bool(re.match(
        r'^(sr\.?|senior|staff|principal|lead)?\s*(software|backend|frontend|fullstack|platform|infrastructure|devops|sre|site reliability)\s+(engineer|developer)',
        title_lower
    ))

    best = 0.0

    for role in profile["_target_roles_lower"]:
        role_tokens = _tokenize(role)
        if not role_tokens:
            continue

        # Strategy 1: Phrase match (contiguous words)
        if _phrase_in_title(role, job_title):
            # If the title STARTS with a SWE role, this is an SWE job that
            # happens to mention data/analytics — penalize heavily
            if title_starts_swe:
                best = max(best, 0.35)
                continue

            # Scale by title length — shorter titles = more focused = higher score
            role_word_count = len(role_tokens)
            title_word_count = len(title_tokens)
            # Base 0.90, bonus up to 0.10 for focused titles
            score = 0.90 + 0.10 * min(role_word_count / title_word_count, 1.0)
            best = max(best, score)
            continue

        # Strategy 2: Jaccard similarity (guarded)
        intersection = title_tokens & role_tokens
        union = title_tokens | role_tokens
        jaccard = len(intersection) / len(union) if union else 0.0

        # If the title has SWE/irrelevant words AND the overlap is just generic
        # tokens like "data" or "engineer", heavily penalize
        if (has_swe_words or has_irrelevant) and jaccard < 0.6:
            jaccard *= 0.3  # e.g., 0.5 → 0.15

        # Cap Jaccard at 0.7 — phrase match is required for higher scores
        score = min(jaccard, 0.70)
        best = max(best, score)

    return best


def score_location_match(job_location: str, profile: dict) -> float:
    """Score location match: exact city > metro > state > relocation > remote > other.

    Returns float [0, 1].
    """
    if not job_location:
        return 0.2  # Default for missing location

    loc_lower = job_location.lower().strip()

    # Remote check
    if "remote" in loc_lower:
        return 1.0 if profile.get("remote_ok") else 0.5

    # Parse profile location
    profile_parts = [p.strip() for p in profile["_location_lower"].split(",")]
    profile_city = profile_parts[0] if profile_parts else ""
    profile_state = profile_parts[1].strip() if len(profile_parts) > 1 else ""

    # Parse job location
    job_parts = [p.strip() for p in loc_lower.split(",")]
    job_city = job_parts[0] if job_parts else ""
    job_state = job_parts[-1].strip() if len(job_parts) > 1 else ""
    # Handle "City, ST" and "City, State, Country" patterns
    if len(job_state) > 2:
        # Try to find a 2-letter state code
        for part in job_parts:
            part = part.strip()
            if len(part) == 2 and part.isalpha():
                job_state = part
                break

    # Exact city match
    if profile_city and profile_city in loc_lower:
        return 1.0

    # Phoenix metro match
    if any(metro_city in loc_lower for metro_city in PHOENIX_METRO):
        return 0.95

    # Same state (word boundary to avoid "az" matching inside longer words)
    if profile_state and re.search(r'\b' + re.escape(profile_state) + r'\b', loc_lower):
        return 0.8

    # Relocation cities
    for reloc_city, reloc_state in profile.get("_relocation_parsed", []):
        if reloc_city in loc_lower:
            return 0.7
        # State match: use word boundary to avoid "ca" matching inside "chicago"
        if reloc_state and re.search(r'\b' + re.escape(reloc_state) + r'\b', loc_lower):
            return 0.6

    # US-based but different state
    us_states = {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
                 "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
                 "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
                 "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
                 "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"}
    if job_state.lower() in us_states:
        return 0.3

    return 0.2  # International or unknown


def score_level_match(job_level: str, profile: dict) -> float:
    """Score level match: exact > one-off > two-off.

    Returns float [0, 1].
    """
    if not job_level:
        return 0.5  # Default for missing level

    target = profile.get("target_level", "mid").lower()
    job_level = job_level.lower()

    if job_level == target:
        return 1.0

    # Level hierarchy for distance calculation
    levels = ["intern", "entry", "mid", "senior", "lead", "manager"]
    try:
        target_idx = levels.index(target)
        job_idx = levels.index(job_level)
        distance = abs(target_idx - job_idx)
    except ValueError:
        return 0.5  # Unknown level

    if distance == 1:
        return 0.7
    elif distance == 2:
        return 0.3
    else:
        return 0.1


def score_keyword_boost(job_title: str, profile: dict) -> float:
    """Count boost_keywords found in job title. Normalized: min(matches / 2, 1.0)."""
    if not job_title:
        return 0.0

    title_lower = job_title.lower()
    matches = sum(1 for kw in profile["_boost_keywords_lower"] if kw in title_lower)
    return min(matches / 2.0, 1.0)


def score_company_preference(job: dict, profile: dict) -> float:
    """Binary: 1.0 if preferred company, 0.0 otherwise.

    Decision 19 from eng review: 3-tier scoring deferred until metadata coverage > 9.8%.
    """
    slug = (job.get("company_slug") or job.get("company") or "").lower()
    # Workday slugs have pipes — match on first part
    slug_parts = slug.split("|")
    slug_normalized = slug_parts[0]

    return 1.0 if slug_normalized in profile.get("_preferred_slugs", set()) else 0.0


def score_recency(scraped_at: str) -> float:
    """Score based on freshness: max(0, 1 - days_since / 30)."""
    if not scraped_at:
        return 0.5  # Default for missing date

    try:
        scraped_dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - scraped_dt).days
        return max(0.0, 1.0 - days / STALE_DAYS)
    except (ValueError, TypeError):
        return 0.5


# ── Main Scoring ───────────────────────────────────────────────────────────────

def score_job(job: dict, profile: dict) -> float:
    """Score a single job against the profile. Returns float [0, 100]."""
    factors = {
        "title_match": score_title_match(job.get("title", ""), profile),
        "location_match": score_location_match(job.get("location", ""), profile),
        "level_match": score_level_match(job.get("skill_level", ""), profile),
        "keyword_boost": score_keyword_boost(job.get("title", ""), profile),
        "company_preference": score_company_preference(job, profile),
        "recency": score_recency(job.get("scraped_at", "")),
    }

    raw = sum(WEIGHTS[k] * factors[k] for k in WEIGHTS)
    return round(raw * 100, 2)


def classify_priority(score: float) -> str:
    """Classify score into priority tier."""
    for tier, (low, high) in PRIORITY_TIERS.items():
        if low <= score <= high:
            return tier
    return "P4"


def should_exclude(job: dict, profile: dict) -> bool:
    """Pre-filter: exclude interns, recruiters, staffing."""
    # Exclude by level
    job_level = (job.get("skill_level") or "").lower()
    exclude_levels = [l.lower() for l in profile.get("exclude_levels", [])]
    if job_level in exclude_levels:
        return True

    # Exclude by intern keyword in title (even if level isn't tagged)
    title = (job.get("title") or "").lower()
    if "intern" in title and profile.get("target_level", "").lower() != "intern":
        return True

    # Exclude recruiter/staffing companies
    if profile.get("exclude_recruiters") and job.get("is_recruiter"):
        return True

    # Exclude blocklisted companies (staffing farms, aggregators)
    company_slug = (job.get("company_slug") or job.get("company") or "").lower().split("|")[0]
    if company_slug in COMPANY_BLOCKLIST:
        return True

    return False


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_matcher(date: str | None = None, min_score: float = 0) -> dict:
    """Score all jobs for a given date, save results.

    Args:
        date: Date string (YYYY-MM-DD). Defaults to today.
        min_score: Minimum score to include in output.

    Returns:
        Summary dict with counts per tier.
    """
    ensure_dirs()
    date_str = date or today()
    input_path = JOBS_DIR / f"{date_str}.json"
    output_path = SCORED_DIR / f"{date_str}.json"

    if not input_path.exists():
        log.error("No job data for %s at %s", date_str, input_path)
        return {"error": f"No job data for {date_str}"}

    profile = load_profile()

    log.info("Loading jobs from %s...", input_path)
    with open(input_path) as f:
        jobs = json.load(f)
    log.info("Loaded %d jobs", len(jobs))

    t0 = time.time()

    # Score all jobs
    scored = []
    excluded = 0
    below_min = 0

    for job in jobs:
        if should_exclude(job, profile):
            excluded += 1
            continue

        score = score_job(job, profile)

        if score < min_score:
            below_min += 1
            continue

        priority = classify_priority(score)
        
        # Only keep P1-P3 in output (P4 is 97%+ of jobs, wastes disk)
        if priority == "P4":
            below_min += 1
            continue
        
        job["_score"] = score
        job["_priority"] = priority
        scored.append(job)

    # Sort by score descending
    scored.sort(key=lambda j: j["_score"], reverse=True)

    elapsed = time.time() - t0

    # Count tiers
    tier_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for job in scored:
        tier_counts[job["_priority"]] = tier_counts.get(job["_priority"], 0) + 1

    # Save scored jobs
    with open(output_path, "w") as f:
        json.dump(scored, f)

    # Write profile metadata sidecar for staleness detection.
    # site_generator and SKILL.md read this to verify scored data
    # was generated against the current profile.
    hash_val = profile_hash()
    target_roles = profile.get("target_roles", [])
    meta = {
        "profile_hash": hash_val,
        "target_roles": target_roles,
        "scored_at": date_str,
        "total_scanned": len(jobs),
        "total_scored": len(scored),
        "tiers": tier_counts,
    }
    meta_path = SCORED_DIR / f"{date_str}.meta.json"
    try:
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
    except (IOError, OSError) as e:
        log.warning("Could not write meta file %s: %s", meta_path, e)

    result = {
        "date": date_str,
        "total_scanned": len(jobs),
        "excluded": excluded,
        "below_min": below_min,
        "scored": len(scored),
        "tiers": tier_counts,
        "elapsed_seconds": round(elapsed, 2),
        "output_path": str(output_path),
        "profile_hash": hash_val,
    }

    log.info("Profile: %s (%s)", hash_val, ", ".join(target_roles[:3]))
    log.info("Scored %d jobs in %.2fs (excluded %d, below-min %d)",
             len(scored), elapsed, excluded, below_min)
    log.info("Tiers: P1=%d, P2=%d, P3=%d, P4=%d",
             tier_counts["P1"], tier_counts["P2"], tier_counts["P3"], tier_counts["P4"])

    return result


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="JobHunter matcher — score and rank jobs")
    parser.add_argument("--date", type=str, default=None, help="Date to score (YYYY-MM-DD)")
    parser.add_argument("--min-score", type=float, default=0, help="Minimum score threshold")
    args = parser.parse_args()

    result = run_matcher(date=args.date, min_score=args.min_score)
    print(f"\n{json.dumps(result, indent=2)}")
