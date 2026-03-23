"""Job-level scoring and ranking engine.

Scores each job against the user's profile, classifies into priority tiers.
Score = weighted sum of: title_match, location_match, level_match,
        keyword_boost, company_preference, recency.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import (
    load_profile, profile_hash, today, ensure_dirs,
    JOBS_DIR, SCORED_DIR, ENRICHED_DIR, WEIGHTS, PRIORITY_TIERS, STALE_DAYS,
    COMPANY_BLOCKLIST, SWE_FAMILY_WORDS,
)

log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

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

    # Check exclude_title_patterns — user-configured negative patterns
    # (e.g., "cloud platform", "devops", "sre") → cap at 0.15
    for pattern in profile.get("_exclude_title_patterns_lower", []):
        if pattern in title_lower:
            return 0.15

    # Check for negative signals — dynamic penalty words (profile-aware)
    # For SWE profiles, SWE words are removed from the penalty set.
    # For BI profiles, SWE words remain as penalties.
    penalty_words = profile.get("_title_penalty_words", SWE_FAMILY_WORDS)
    has_swe_words = bool(title_tokens & penalty_words)
    has_irrelevant = bool(title_tokens & IRRELEVANT_WORDS)

    # Check if title starts with a SWE role (e.g., "Software Engineer ... Data Engineering")
    # Skip this check if the user's target roles include SWE-family titles
    if penalty_words:
        title_starts_swe = bool(re.match(
            r'^(sr\.?|senior|staff|principal|lead)?\s*(software|backend|frontend|fullstack|platform|infrastructure|devops|sre|site reliability)\s+(engineer|developer)',
            title_lower
        ))
    else:
        title_starts_swe = False

    best = 0.0

    for role in profile["_target_roles_lower"]:
        role_tokens = _tokenize(role)
        if not role_tokens:
            continue

        # Strategy 1: Phrase match (contiguous words)
        if _phrase_in_title(role, job_title):
            # Phrase match succeeded — this is a genuine title match.
            # Only apply cross-family SWE penalty when the matched role is NOT
            # SWE-family AND the title starts with a SWE role — this catches
            # false positives like "Software Engineer - Data Analytics" matching
            # "Data Analyst". If the user's role IS SWE-family (e.g., "Backend
            # Engineer", "Senior Software Engineer"), skip the penalty entirely
            # because phrase match already proves correct family alignment.
            role_is_swe = bool(role_tokens & {"software", "backend", "frontend",
                "fullstack", "platform", "infrastructure", "devops", "sre",
                "systems", "engineer", "developer"})
            if title_starts_swe and not role_is_swe:
                # Cross-family false positive: SWE title matched a non-SWE role
                best = max(best, 0.35)
                continue
            # For SWE roles (the common case): phrase match is sufficient proof,
            # skip the penalty regardless of title_starts_swe. This prevents
            # "Senior Software Engineer, Cloud Infrastructure" from being penalized
            # just because "infrastructure" is in penalty_words.

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

    # Metro area match (profile-configured, replaces hardcoded PHOENIX_METRO)
    metro_cities = profile.get("_metro_cities_lower", set())
    if metro_cities and any(metro_city in loc_lower for metro_city in metro_cities):
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
    """Count boost_keywords (+ auto-merged skills) found in job title.

    Uses word-boundary matching to prevent short keywords (e.g. "R", "Go")
    from false-matching inside longer words ("developer", "algorithm").
    Normalized: min(matches / 2, 1.0).
    """
    if not job_title:
        return 0.0

    title_lower = job_title.lower()
    matches = sum(
        1 for kw in profile["_boost_keywords_lower"]
        if re.search(r'\b' + re.escape(kw) + r'\b', title_lower)
    )
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
    """Score a single job against the profile. Returns float [0, 100].

    Side effect: stores _title_match factor (0-1) on job dict for downstream
    LLM re-scoring in apply_enrichment().
    """
    factors = {
        "title_match": score_title_match(job.get("title", ""), profile),
        "location_match": score_location_match(job.get("location", ""), profile),
        "level_match": score_level_match(job.get("skill_level", ""), profile),
        "keyword_boost": score_keyword_boost(job.get("title", ""), profile),
        "company_preference": score_company_preference(job, profile),
        "recency": score_recency(job.get("scraped_at", "")),
    }

    # Store title_match for downstream LLM re-scoring
    job["_title_match"] = factors["title_match"]

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

    # Apply enrichment blending if enriched sidecar exists
    scored, enriched_count = apply_enrichment(scored, date_str)
    if enriched_count:
        log.info("Blended enriched scores for %d jobs", enriched_count)
        # Re-sort after blending (scores may have changed)
        scored.sort(key=lambda j: j["_score"], reverse=True)
    else:
        # Sort by score descending (no enrichment)
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


# ── Enriched Score Blending ───────────────────────────────────────────────────
#
# When enriched description data is available (from src/enricher.py), the
# title-based score is blended with the skill match percentage:
#
#   blended = 0.70 × title_score + 0.30 × skill_match_pct
#
# This gives description-derived skill match 30% weight. The 70/30 split is
# conservative — title matching is still the primary signal since descriptions
# can be noisy and the skill extraction is regex-based (not LLM).
#
# Jobs without enrichment (unenriched=True or missing from enriched sidecar)
# keep their original title-based score — no re-rank, no penalty.
#
# Blend diagram:
#
#   title_score (0-100)      skill_match_pct (0-100)
#        │                           │
#        ▼ ×0.70                     ▼ ×0.30
#        └─────────────┬─────────────┘
#                   blended_score
#                      │
#               classify_priority()
#
ENRICHED_BLEND_WEIGHT = 0.30  # weight of skill_match_pct in blended score


def blend_enriched_score(title_score: float, skill_match_pct: int) -> float:
    """Blend title-based score with description skill match percentage.

    Args:
        title_score: Original 0-100 score from score_job()
        skill_match_pct: 0-100 integer from enricher (% required skills matched)

    Returns:
        Blended score 0-100, rounded to 2 decimal places.
    """
    blended = (
        (1 - ENRICHED_BLEND_WEIGHT) * title_score
        + ENRICHED_BLEND_WEIGHT * skill_match_pct
    )
    return round(blended, 2)


def _try_llm_title_rescore(jobs: list[dict], profile: dict) -> dict[str, float]:
    """Attempt LLM-based title re-scoring for P1+P2 jobs.

    Returns {url: llm_title_score} for jobs where LLM succeeded.
    Empty dict if LLM unavailable. Only runs on P1+P2 (~1,200 jobs).
    """
    try:
        from src.llm import batch_classify_titles, is_available
        if not is_available():
            return {}
        target_roles = profile.get("target_roles", [])
        if not target_roles:
            return {}
        return batch_classify_titles(jobs, target_roles)
    except ImportError:
        return {}
    except Exception as e:
        log.debug("LLM title rescore failed: %s", e)
        return {}


def apply_enrichment(scored: list[dict], date_str: str) -> tuple[list[dict], int]:
    """Re-score enriched jobs with blended scores. Modifies list in-place.

    Reads enriched sidecar (data/enriched/DATE.json) if present.
    When ANTHROPIC_API_KEY is set, also re-scores title matches using
    Claude for semantic accuracy (regex → LLM upgrade for P1+P2 only).
    Jobs without enrichment keep their original scores — no penalty.

    Args:
        scored: List of scored job dicts (with _score, _priority fields).
        date_str: Date string to find the enriched sidecar.

    Returns:
        (scored, enriched_count) — same list with blended scores applied.
    """
    enriched_path = ENRICHED_DIR / f"{date_str}.json"
    if not enriched_path.exists():
        return scored, 0

    try:
        with open(enriched_path) as f:
            enriched = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not load enriched data: %s", e)
        return scored, 0

    # Optional: LLM title re-scoring for P1+P2 jobs
    p1p2_jobs = [j for j in scored if j.get("_priority") in ("P1", "P2")]
    try:
        profile = load_profile()
        llm_title_scores = _try_llm_title_rescore(p1p2_jobs, profile)
    except Exception:
        llm_title_scores = {}

    if llm_title_scores:
        log.info("LLM re-scored %d P1+P2 job titles", len(llm_title_scores))

    enriched_count = 0
    for job in scored:
        url = job.get("url", "")

        # Apply LLM title re-score if available (replaces regex title_match)
        if url in llm_title_scores:
            llm_score = llm_title_scores[url]
            # LLM score is 0-1, title_match weight is 35% of total
            # Recalculate: replace title_match component with LLM score
            old_title_contribution = WEIGHTS["title_match"] * job.get("_title_match", 0)
            new_title_contribution = WEIGHTS["title_match"] * llm_score
            adjustment = (new_title_contribution - old_title_contribution) * 100
            job["_score"] = round(job["_score"] + adjustment, 2)
            job["_llm_title_score"] = llm_score
            job["_priority"] = classify_priority(job["_score"])

        enrich = enriched.get(url, {})
        if not enrich or enrich.get("unenriched") or enrich.get("skill_match_pct") is None:
            continue  # no enrichment — keep original score

        skill_match_pct = enrich["skill_match_pct"]
        if skill_match_pct == 0:
            continue  # no required skills found — don't penalize

        original_score = job["_score"]
        blended = blend_enriched_score(original_score, skill_match_pct)
        job["_score"] = blended
        job["_priority"] = classify_priority(blended)
        job["_skill_match_pct"] = skill_match_pct
        enriched_count += 1

    return scored, enriched_count


# ── Browsed Job Integration ───────────────────────────────────────────────────
#
# Browsed jobs (from gstack /browse) are scored and merged into the daily
# scored data so they appear in reports, dashboard, and /classify-jobs.
#
#   Browse text ──▶ Claude extracts fields ──▶ score_and_save_browsed()
#                                                    │
#                                    ┌───────────────┤
#                                    ▼               ▼
#                              score_job()    append to data/scored/DATE.json
#                              classify()     (dedup by URL, tagged _source=browse)

def score_and_save_browsed(job_dict: dict, date: str | None = None) -> dict:
    """Score a single browsed job and append it to today's scored data.

    Args:
        job_dict: Job dict with at minimum: title, company, url.
                  Optional: location, skill_level, ats, scraped_at.
        date: Date string (YYYY-MM-DD). Defaults to today.

    Returns:
        The job dict with _score, _priority, and _source fields added.

    Raises:
        ValueError: If required fields (title, company, url) are missing.
    """
    ensure_dirs()

    # Validate required fields
    required = ["title", "company", "url"]
    missing = [f for f in required if not job_dict.get(f)]
    if missing:
        raise ValueError(f"Browsed job missing required fields: {missing}")

    # Apply safe defaults for optional fields
    job = dict(job_dict)
    job.setdefault("location", "")
    job.setdefault("skill_level", "")
    job.setdefault("ats", "browse")
    job.setdefault("is_recruiter", False)
    job.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())

    # Score against profile
    profile = load_profile()
    score = score_job(job, profile)
    priority = classify_priority(score)

    job["_score"] = score
    job["_priority"] = priority
    job["_source"] = "browse"

    # Append to today's scored data (dedup by URL)
    date_str = date or today()
    scored_path = SCORED_DIR / f"{date_str}.json"

    if scored_path.exists():
        with open(scored_path) as f:
            scored = json.load(f)
    else:
        scored = []

    # Remove existing entry with same URL (re-browse updates the score)
    job_url = job["url"]
    scored = [j for j in scored if j.get("url") != job_url]

    scored.append(job)
    scored.sort(key=lambda j: j.get("_score", 0), reverse=True)

    with open(scored_path, "w") as f:
        json.dump(scored, f)

    log.info("Browsed job scored: %s @ %s → %.1f (%s)",
             job["title"], job["company"], score, priority)

    return job


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
    parser.add_argument(
        "--reblend", action="store_true",
        help="Re-apply enrichment blending to existing scored data (no full re-score). "
             "Run this after src.enricher to blend description skill match into scores."
    )
    args = parser.parse_args()

    if args.reblend:
        # Fast path: just blend enrichment into existing scored data
        date_str = args.date or today()
        scored_path = SCORED_DIR / f"{date_str}.json"
        if not scored_path.exists():
            print(f"No scored data for {date_str}")
            sys.exit(1)
        with open(scored_path) as f:
            scored = json.load(f)
        scored, count = apply_enrichment(scored, date_str)
        if count:
            # Re-sort and update tier counts after blending
            scored.sort(key=lambda j: j["_score"], reverse=True)
            for job in scored:
                job["_priority"] = classify_priority(job["_score"])
            with open(scored_path, "w") as f:
                json.dump(scored, f)
            tier_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
            for job in scored:
                tier_counts[job["_priority"]] = tier_counts.get(job["_priority"], 0) + 1
            print(json.dumps({
                "date": date_str, "reblended": count,
                "tiers": tier_counts,
            }, indent=2))
        else:
            print(f"No enrichment data found for {date_str} — nothing to blend")
    else:
        result = run_matcher(date=args.date, min_score=args.min_score)
        print(f"\n{json.dumps(result, indent=2)}")
