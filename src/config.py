"""Shared configuration — single source of truth for paths, constants, and profile loading."""

import hashlib
import os
import re
import yaml
from datetime import datetime, date
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
JBA_DIR = DATA_DIR / "jba"
JOBS_DIR = DATA_DIR / "jobs"
SCORED_DIR = DATA_DIR / "scored"
REPORTS_DIR = DATA_DIR / "reports"
SRC_DIR = PROJECT_ROOT / "src"

# ── Constants ──────────────────────────────────────────────────────────────────
DATE_FMT = "%Y-%m-%d"
STALE_DAYS = 30  # Jobs older than this get pruned
MIN_JBA_JOBS = 100_000  # Validation gate: JBA download must exceed this
DOWNLOAD_WORKERS = 10
SCRAPE_WORKERS = 30
SCRAPE_WORKERS_BAMBOO = 10

# Scoring weights (must sum to 1.0)
WEIGHTS = {
    "title_match": 0.35,
    "location_match": 0.20,
    "level_match": 0.15,
    "keyword_boost": 0.15,
    "company_preference": 0.15,
    "recency": 0.00,
}

# Priority tier thresholds
PRIORITY_TIERS = {
    "P1": (85, 100),
    "P2": (70, 84.999),
    "P3": (50, 69.999),
    "P4": (0, 49.999),
}

# Titles containing these words are a DIFFERENT job family — penalize hard.
# Moved here from matcher.py to avoid circular import (config ← matcher ← config).
SWE_FAMILY_WORDS = {
    "software", "backend", "frontend", "fullstack", "full-stack", "devops",
    "sre", "ios", "android", "mobile", "web", "react", "node", "java",
    "ruby", "golang", "rust", "php", "net", "dotnet", "embedded",
    "backline", "infrastructure", "platform", "reliability", "security",
    "network", "systems", "cloud", "kubernetes", "ml",
}

# Company blocklist — staffing farms and aggregators that pollute results
COMPANY_BLOCKLIST = {
    "jobgether",           # Job aggregator (19K+ listings, not a real employer)
    "launch2",             # Staffing firm
    "globalhr",            # HR/staffing aggregator
    "ghr",                 # Staffing
    "svetness",            # Personal training franchise (mass-posts irrelevant jobs)
    "bluelightconsulting",  # Staffing (already flagged is_recruiter but belt-and-suspenders)
    "tsmg",                # Staffing
    "pae",                 # Staffing/contracting
}

# JBA GitHub repo info
JBA_REPO = "Feashliaa/job-board-aggregator"
JBA_BRANCH = "main"
JBA_DATA_PATH = "data"


# ── Profile Loading ───────────────────────────────────────────────────────────
def _normalize_profile(profile: dict) -> dict:
    """Apply defaults and build computed fields for a profile dict.

    Shared by load_profile() (file-based) and load_profile(raw=...) (dict-based).
    Tests use raw= to avoid file I/O while sharing the same normalization logic.
    """
    # Defaults for optional fields
    profile.setdefault("remote_ok", True)
    profile.setdefault("willing_to_relocate", False)
    profile.setdefault("relocation_cities", [])
    profile.setdefault("years_experience", 0)
    profile.setdefault("target_level", "mid")
    profile.setdefault("exclude_levels", ["intern"])
    profile.setdefault("boost_keywords", [])
    profile.setdefault("preferred_companies", {})
    profile.setdefault("exclude_recruiters", True)
    profile.setdefault("exclude_staffing", True)
    profile.setdefault("exclude_title_patterns", [])
    profile.setdefault("metro_cities", [])

    # Normalize text fields for matching
    profile["_target_roles_lower"] = [r.lower() for r in profile["target_roles"]]
    profile["_skills_lower"] = [s.lower() for s in profile["skills"]]
    profile["_boost_keywords_lower"] = [k.lower() for k in profile["boost_keywords"]]
    profile["_location_lower"] = profile["location"].lower()

    # Parse relocation cities into (city, state) tuples
    profile["_relocation_parsed"] = []
    for city in profile.get("relocation_cities", []):
        parts = [p.strip().lower() for p in city.split(",")]
        if len(parts) == 2:
            profile["_relocation_parsed"].append((parts[0], parts[1]))

    # Build flat set of preferred company slugs for O(1) lookup
    profile["_preferred_slugs"] = set()
    for platform, slugs in profile.get("preferred_companies", {}).items():
        for slug in slugs:
            # Workday slugs have pipes — use first part as identifier
            profile["_preferred_slugs"].add(slug.split("|")[0].lower())

    # Normalize exclude_title_patterns for O(n) matching
    profile["_exclude_title_patterns_lower"] = [
        p.lower() for p in profile.get("exclude_title_patterns", [])
    ]

    # Normalize metro cities for location matching
    profile["_metro_cities_lower"] = {
        c.strip().lower() for c in profile.get("metro_cities", [])
    }

    # Build dynamic title penalty words — SWE_FAMILY_WORDS minus words in target roles.
    # For a Backend SWE profile, "backend", "software", "platform" are removed from
    # the penalty set. For a BI profile, they stay (SWE titles are false positives).
    target_words = set()
    for role in profile["_target_roles_lower"]:
        target_words.update(re.findall(r'[a-z0-9]+', role))
    profile["_title_penalty_words"] = SWE_FAMILY_WORDS - target_words

    return profile


def load_profile(path: str | Path | None = None, *, raw: dict | None = None) -> dict:
    """Load and validate user profile from YAML file or raw dict.

    Args:
        path: Path to profile YAML. Defaults to config/profile.yaml.
        raw: Pre-loaded profile dict (skips file I/O). Used by tests.
             If both path and raw are provided, raw takes precedence.

    Returns:
        Validated and normalized profile dict.

    Raises:
        FileNotFoundError: If profile file doesn't exist (file mode only).
        ValueError: If required fields are missing.
    """
    if raw is not None:
        profile = dict(raw)  # shallow copy to avoid mutating caller's dict
    else:
        if path is None:
            path = CONFIG_DIR / "profile.yaml"
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {path}")

        with open(path) as f:
            profile = yaml.safe_load(f)

    # Validate required fields
    required = ["name", "location", "target_roles", "skills"]
    missing = [f for f in required if f not in profile or not profile[f]]
    if missing:
        raise ValueError(f"Profile missing required fields: {missing}")

    return _normalize_profile(profile)


def profile_hash(path: "str | Path | None" = None) -> str:
    """8-char sha256 of raw profile.yaml content.

    Changes whenever ANY field in profile.yaml changes, signalling that
    scored data generated against a different profile version is now stale.

    A Business Intelligence analyst and a Fashion Designer produce completely
    different scored datasets from the same 502K jobs — because title_match
    (35% of score) runs phrase-matching against target_roles, and keyword_boost
    (15%) runs against skills + boost_keywords.

    Returns '00000000' if profile.yaml does not exist or cannot be read.
    """
    if path is None:
        path = CONFIG_DIR / "profile.yaml"
    path = Path(path)
    try:
        content = path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()[:8]
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        return "00000000"


def today() -> str:
    """Today's date as YYYY-MM-DD string."""
    return date.today().strftime(DATE_FMT)


def ensure_dirs():
    """Create all data directories if they don't exist."""
    for d in [SEED_DIR, JBA_DIR, JOBS_DIR, SCORED_DIR, REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
