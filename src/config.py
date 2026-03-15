"""Shared configuration — single source of truth for paths, constants, and profile loading."""

import os
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
    "company_preference": 0.10,
    "recency": 0.05,
}

# Priority tier thresholds
PRIORITY_TIERS = {
    "P1": (85, 100),
    "P2": (70, 84.999),
    "P3": (50, 69.999),
    "P4": (0, 49.999),
}

# Phoenix metro area cities for location matching
PHOENIX_METRO = {
    "phoenix", "tempe", "scottsdale", "mesa", "chandler", "gilbert",
    "glendale", "peoria", "surprise", "avondale", "goodyear", "buckeye",
    "queen creek", "maricopa", "fountain hills", "cave creek", "carefree",
}

# JBA GitHub repo info
JBA_REPO = "Feashliaa/job-board-aggregator"
JBA_BRANCH = "main"
JBA_DATA_PATH = "data"


# ── Profile Loading ───────────────────────────────────────────────────────────
def load_profile(path: str | Path | None = None) -> dict:
    """Load and validate user profile from YAML.

    Args:
        path: Path to profile YAML. Defaults to config/profile.yaml.

    Returns:
        Validated profile dict.

    Raises:
        FileNotFoundError: If profile doesn't exist.
        ValueError: If required fields are missing.
    """
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

    return profile


def today() -> str:
    """Today's date as YYYY-MM-DD string."""
    return date.today().strftime(DATE_FMT)


def ensure_dirs():
    """Create all data directories if they don't exist."""
    for d in [SEED_DIR, JBA_DIR, JOBS_DIR, SCORED_DIR, REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
