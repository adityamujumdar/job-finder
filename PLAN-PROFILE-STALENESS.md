# Plan: Profile Staleness Detection — SCOPE EXPANSION

**Date:** 2026-03-16
**Status:** Reviewed (CEO + Eng), approved, ready to implement
**Touches:** 7 files, 0 new classes, 1 new data artifact (meta.json)
**Tests:** 9 new unit tests
**Estimated effort:** ~2 hours

---

## Problem Statement

When a user edits `config/profile.yaml` (e.g., changes target_roles from "BI Analyst" to "Fashion Designer"), all existing scored data in `data/scored/` becomes silently stale. No warning. No signal to check. The dashboard shows results for the wrong profile. This is a zero-feedback failure.

---

## Solution Overview

```
  config/profile.yaml ──sha256──▶ PROFILE_HASH (8 chars, e.g. "a1b2c3d4")
         │
         ▼
  ┌─────────────────────┐     writes      ┌──────────────────────────────┐
  │  src/matcher.py     │ ──────────────▶ │ data/scored/DATE.json        │
  │  run_matcher()      │                 │ (unchanged format)           │
  └─────────┬───────────┘                 └──────────────────────────────┘
            │ writes
            ▼
  ┌─────────────────────────────┐
  │ data/scored/DATE.meta.json  │   ◀── NEW: sidecar meta file
  │ {                           │
  │   "profile_hash": "a1b2c3d4"│
  │   "target_roles": [...]     │
  │   "scored_at": "2026-03-16" │
  │   "total_scored": 8215      │
  │   "tiers": {"P1":51,...}    │
  │ }                           │
  └─────────┬───────────────────┘
            │ read + compare
            ▼
  ┌─────────────────────────────┐
  │  src/site_generator.py      │
  │  1. Read meta file          │
  │  2. Compare profile_hash()  │
  │     vs stored hash          │
  │  3a. Match → show           │
  │      "Scored against: X"    │
  │  3b. Mismatch → auto-       │
  │      rescore, then generate │
  │  3c. No meta → warn/rescore │
  └─────────────────────────────┘
```

---

## Deliverables (7 files)

### 1. `src/config.py` — Harden profile_hash()

**Current state:** `profile_hash()` exists (uncommitted, +23 lines). Returns 8-char sha256 of profile.yaml content. Returns `"00000000"` if file missing.

**Changes needed:**
- Add try/except for `PermissionError` and `UnicodeDecodeError` → return `"00000000"`
- Move `import hashlib` to module top level (stdlib, no cost)
- Keep existing behavior: returns `"00000000"` for missing file

```python
# src/config.py — at module top
import hashlib

def profile_hash(path: "str | Path | None" = None) -> str:
    """8-char sha256 of raw profile.yaml content.
    
    Changes whenever ANY field in profile.yaml changes, signalling that
    scored data generated against a different profile version is now stale.
    
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
```

### 2. `src/matcher.py` — Write meta file + log profile fingerprint

**Changes to `run_matcher()`:**
After writing `data/scored/DATE.json`, also write `data/scored/DATE.meta.json`:

```python
# After the existing json.dump(scored, f) block:

# Write profile metadata for staleness detection
from src.config import profile_hash
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
    log.info("Profile: %s (%s)", hash_val, ", ".join(target_roles[:3]))
except (IOError, OSError) as e:
    log.warning("Could not write meta file %s: %s", meta_path, e)
```

**Import change:** Add `profile_hash` to the import from `src.config`.

**Add to result dict:**
```python
result["profile_hash"] = hash_val
```

### 3. `src/site_generator.py` — Read meta + staleness check + auto-rescore

**Fix first:** Remove duplicate `_build_html` definition (lines 138-140). The first definition:
```python
def _build_html(*, jobs_json, date_str, p1, p2, p3, new_count, total,
                top_companies, profile_name, profile_roles) -> str:
    """Build the full HTML dashboard with company/location/ATS dropdown filters."""
```
is immediately overwritten by lines 141-143. Delete lines 138-140.

**New function: `_check_staleness()`**

```python
def _check_staleness(date_str: str) -> dict:
    """Check if scored data matches current profile.
    
    Returns dict with:
      - "status": "fresh" | "stale" | "unknown"
      - "stored_hash": str or None
      - "current_hash": str
      - "stored_roles": list or None
    """
    from src.config import profile_hash
    
    current_hash = profile_hash()
    meta_path = SCORED_DIR / f"{date_str}.meta.json"
    
    if not meta_path.exists():
        return {
            "status": "unknown",
            "stored_hash": None,
            "current_hash": current_hash,
            "stored_roles": None,
        }
    
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        stored_hash = meta.get("profile_hash", "")
        stored_roles = meta.get("target_roles", [])
        status = "fresh" if stored_hash == current_hash else "stale"
        return {
            "status": status,
            "stored_hash": stored_hash,
            "current_hash": current_hash,
            "stored_roles": stored_roles,
        }
    except (json.JSONDecodeError, OSError, KeyError):
        return {
            "status": "unknown",
            "stored_hash": None,
            "current_hash": current_hash,
            "stored_roles": None,
        }
```

**Modify `generate_site()`:**

After loading scored jobs, before rendering HTML:

```python
# Check profile staleness — warn only, do NOT auto-rescore.
# Rescoring is the SKILL.md orchestration layer's job, not site_generator's.
# This keeps the dependency graph clean: site_generator never imports matcher.
staleness = _check_staleness(date_str)

if staleness["status"] == "stale":
    log.warning("⚠️  Profile changed since last score (stored: %s, current: %s). "
                "Dashboard may show stale results. Re-run: python -m src.matcher",
                staleness["stored_hash"], staleness["current_hash"])

elif staleness["status"] == "unknown":
    log.warning("ℹ️  No meta file for %s — cannot verify profile match.", date_str)
```

**Modify `_build_html()` signature:**

Add `staleness_status` parameter. In the subtitle:

```python
# Fresh: show "✅ Scored against: BI Developer, Data Analyst"
# Stale: show "⚠️ Rescored — profile changed since last run"  
# Unknown: show just the roles (no indicator)
if staleness_status == "fresh":
    profile_indicator = f"✅ {html.escape(profile_roles)}"
elif staleness_status == "rescored":
    profile_indicator = f"🔄 Rescored — {html.escape(profile_roles)}"
else:
    profile_indicator = html.escape(profile_roles)
```

### 4. `CLAUDE.md` — Add Critical Rules section

Add after the "Known Gotchas" section:

```markdown
## Critical Rules

1. **Profile staleness check:** Before showing scored results, running the report, 
   or generating the dashboard, verify freshness:
   ```python
   from src.config import profile_hash
   import json
   meta = json.load(open(f"data/scored/{date}.meta.json"))
   if meta["profile_hash"] != profile_hash():
       # Profile changed — rescore before showing results
       python -m src.matcher
   ```
   If `data/scored/DATE.meta.json` doesn't exist, rescore first.
   If profile_hash doesn't match, rescore first.
   **Never show scored results without verifying the profile hash.**
```

### 5. `jobhunter/SKILL.md` — Add staleness check to Step 0

Add to the Step 0 prerequisite check bash block:

```bash
# Profile staleness check
python3 -c "
import json, sys
from src.config import profile_hash, SCORED_DIR, today
meta_path = SCORED_DIR / f'{today()}.meta.json'
if meta_path.exists():
    meta = json.load(open(meta_path))
    current = profile_hash()
    if meta.get('profile_hash') != current:
        print(f'⚠️  Profile changed since last score (was {meta[\"profile_hash\"]}, now {current}). Will rescore.')
        sys.exit(1)
    else:
        print(f'✅ Profile hash: {current} (matches scored data)')
else:
    print('ℹ️  No scored data yet — will score fresh')
" 2>/dev/null || echo "⚠️  Profile may have changed — will rescore during pipeline"
```

Add to Step 2 (Match) instructions: "This step also writes `data/scored/DATE.meta.json` with the profile fingerprint for staleness detection."

### 6. `config/profile.yaml.example` — Rich scoring-impact comments

```yaml
# JobHunter AI — User Profile
# Copy this to profile.yaml and customize.
#
# Every field here affects how 502K+ jobs are scored and ranked.
# After editing, re-run the pipeline: python -m src.matcher
# (or just run /jobhunter — it auto-detects profile changes)

name: "Your Name"
email: "you@example.com"

# Your current city. Jobs here score 1.0 on location (20% of total score).
# Nearby metro cities score 0.95. Same state scores 0.8.
location: "City, ST"

willing_to_relocate: true

# Cities you'd move to. Jobs in these cities score 0.7 on location.
# Jobs in the same STATE as a relocation city score 0.6.
relocation_cities:
  - "San Francisco, CA"
  - "New York, NY"

# If true, "Remote" jobs score 1.0 on location (same as your home city).
remote_ok: true

years_experience: 3

# Target seniority. Exact match = 1.0 (15% of score).
# One level off (e.g., "mid" target but "senior" job) = 0.7.
# Options: intern, entry, mid, senior, lead, manager
target_level: "mid"

# Jobs at these levels are excluded entirely (pre-filter, not scored).
exclude_levels: ["intern"]

# ⭐ MOST IMPORTANT FIELD — drives 35% of your score (title_match).
# Each role is matched as a PHRASE against job titles.
# "Data Engineer" matches "Senior Data Engineer" but NOT "Data Center Engineer".
# BI ↔ "Business Intelligence" expansion is automatic.
# Add more roles = cast a wider net. Be specific: "BI Analyst" > "Analyst".
target_roles:
  - "Software Engineer"
  - "Backend Engineer"

# Technical skills. Currently used for keyword_boost (15% of score).
# These are matched against job titles. More matches = higher boost.
skills:
  - Python
  - Go
  - PostgreSQL

# Keywords that boost score when found in job TITLE (not description).
# Each keyword found adds to keyword_boost (15% of score).
# Normalized: min(matches / 2, 1.0) — so 2+ matches = full boost.
boost_keywords:
  - "backend"
  - "distributed"
  - "systems"

# Companies to live-scrape for freshest data (10% of score as company_preference).
# Jobs at preferred companies get company_preference = 1.0 (vs 0.0 for others).
# Use the ATS slug from their careers page URL.
preferred_companies:
  greenhouse:
    - "anthropic"     # jobs.greenhouse.io/anthropic
    - "stripe"        # jobs.greenhouse.io/stripe
  lever:
    - "netflix"       # jobs.lever.co/netflix
  # workday format: "company|instance|site"
  # Example: "nvidia|wd5|NVIDIAExternalCareerSite"
  # ashby: just the slug from jobs.ashby.io/SLUG

exclude_recruiters: true    # Filter out staffing/recruiting companies
exclude_staffing: true      # Filter out known staffing farms (jobgether, etc.)
```

### 7. Tests — 9 new unit tests

**File:** `tests/unit/test_profile_staleness.py`

```python
"""Tests for profile staleness detection: hash, meta file, and staleness check."""

import json
import pytest
from pathlib import Path


class TestProfileHash:
    """Tests for config.profile_hash()."""

    def test_returns_8_char_hex(self, tmp_path):
        """profile_hash returns an 8-character hex string."""
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test\ntarget_roles:\n  - Engineer\n")
        from src.config import profile_hash
        result = profile_hash(path=profile)
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_returns_zeros_for_missing_file(self, tmp_path):
        """profile_hash returns '00000000' when file doesn't exist."""
        from src.config import profile_hash
        result = profile_hash(path=tmp_path / "nonexistent.yaml")
        assert result == "00000000"

    def test_changes_when_content_changes(self, tmp_path):
        """profile_hash changes when profile content changes."""
        profile = tmp_path / "profile.yaml"
        profile.write_text("target_roles:\n  - BI Analyst\n")
        from src.config import profile_hash
        hash1 = profile_hash(path=profile)
        
        profile.write_text("target_roles:\n  - Fashion Designer\n")
        hash2 = profile_hash(path=profile)
        assert hash1 != hash2

    def test_stable_for_identical_content(self, tmp_path):
        """profile_hash returns same value for identical content."""
        profile = tmp_path / "profile.yaml"
        content = "name: Test\ntarget_roles:\n  - Engineer\n"
        profile.write_text(content)
        from src.config import profile_hash
        hash1 = profile_hash(path=profile)
        hash2 = profile_hash(path=profile)
        assert hash1 == hash2


class TestMetaFileWrite:
    """Tests for matcher writing .meta.json alongside scored data."""

    def test_run_matcher_writes_meta_file(self, tmp_path, monkeypatch):
        """run_matcher() creates a .meta.json sidecar with profile hash."""
        # Setup: create minimal job data and profile
        # ... (mock JOBS_DIR, SCORED_DIR, profile loading)
        # Assert: meta file exists, contains profile_hash, target_roles, scored_at
        pass  # Implement with proper fixtures

    def test_meta_file_contains_required_fields(self, tmp_path):
        """Meta file has: profile_hash, target_roles, scored_at, total_scored, tiers."""
        # ... verify all fields present
        pass  # Implement with proper fixtures


class TestStalenessCheck:
    """Tests for site_generator._check_staleness()."""

    def test_fresh_when_hash_matches(self, tmp_path):
        """Returns 'fresh' when profile hash matches meta file."""
        # Write a meta file with known hash
        # Mock profile_hash to return same hash
        # Assert status == "fresh"
        pass

    def test_stale_when_hash_mismatches(self, tmp_path):
        """Returns 'stale' when profile hash differs from meta file."""
        # Write a meta file with hash "aaaaaaaa"
        # Mock profile_hash to return "bbbbbbbb"
        # Assert status == "stale"
        pass

    def test_unknown_when_meta_missing(self, tmp_path):
        """Returns 'unknown' when meta file doesn't exist."""
        # No meta file on disk
        # Assert status == "unknown"
        pass
```

---

## Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| profile.yaml missing | `profile_hash()` returns `"00000000"`. SKILL.md Step 0 catches this (hard stop). |
| profile.yaml unreadable (permissions) | `profile_hash()` catches `PermissionError`, returns `"00000000"`. |
| Meta file missing (first run) | `_check_staleness()` returns `"unknown"`. site_generator rescores. |
| Meta file corrupt JSON | `_check_staleness()` catches `JSONDecodeError`, returns `"unknown"`. |
| Comment-only change to profile.yaml | Hash changes → rescore triggered. Acceptable false positive (~8s). |
| profile.yaml whitespace change | Hash changes → rescore triggered. Acceptable false positive. |
| Meta file write fails (disk full) | Matcher catches IOError, logs warning, continues. Scoring still works. |

---

## NOT in Scope

| Item | Rationale |
|---|---|
| Semantic hashing (hash only scoring fields) | Comment-only false positives acceptable; full-content hash is simpler |
| Profile version history | Nice-to-have, not needed for staleness detection |
| CI/CD staleness gate | Overkill for a personal tool |
| Auto-rescore in GitHub Actions | Cron always runs full pipeline anyway |

---

## Build Order

```
  Step 1 (~10 min): Harden profile_hash() in src/config.py
    └── Add try/except, move import to top

  Step 2 (~20 min): Add meta file write to src/matcher.py
    └── Write DATE.meta.json after scoring
    └── Add profile fingerprint log line
    └── Add profile_hash to result dict

  Step 3 (~40 min): Staleness check + auto-rescore in src/site_generator.py
    └── Fix duplicate _build_html definition
    └── Add _check_staleness() function
    └── Auto-rescore on stale/unknown
    └── Add staleness indicator to dashboard subtitle

  Step 4 (~10 min): CLAUDE.md Critical Rules section
    └── Add profile staleness rule

  Step 5 (~10 min): jobhunter/SKILL.md Step 0 update
    └── Add staleness check bash block

  Step 6 (~10 min): Enrich config/profile.yaml.example
    └── Add scoring-impact comments per field

  Step 7 (~20 min): Write 9 unit tests
    └── tests/unit/test_profile_staleness.py

  TOTAL: ~2 hours
```

---

## Verification Checklist

After implementation:
- [ ] `pytest tests/unit/` — all tests pass (existing 95 + 9 new = 104)
- [ ] `python -m src.matcher` — writes `data/scored/DATE.meta.json`
- [ ] `cat data/scored/DATE.meta.json` — contains profile_hash, target_roles
- [ ] Edit `config/profile.yaml` (add a comment) → `python -m src.site_generator` → auto-rescores
- [ ] Dashboard subtitle shows "✅ Scored against: BI Developer, Data Analyst, ..."
- [ ] `grep "Critical Rules" CLAUDE.md` — rule exists
- [ ] `diff config/profile.yaml.example` — has scoring comments
