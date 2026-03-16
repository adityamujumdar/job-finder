# JobHunter AI — Plan v3 (Post Eng Review)

## Executive Summary

A Claude skill that automates job discovery across 502K+ jobs from 12K+ companies, with personalized matching and daily reports. Built on the [job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) (JBA) dataset + live scraping for preferred companies.

**Key insight from Eng Review:** JBA already scrapes daily and publishes 502K jobs on GitHub. We download that (~15s) for massive coverage, then live-scrape preferred companies for freshness. This hybrid approach gives us 502K jobs in 30 seconds + fresh data for companies that matter.

---

## Engineering Review Findings

### Finding 1: JBA Pre-Scraped Data is a Game Changer
**Measured:** JBA publishes 502,747 jobs daily as gzipped JSON on GitHub. Download takes ~15 seconds (17MB compressed). Data includes: title, company, location, url, ats, skill_level, is_recruiter, scraped_at.

**Impact on plan:** MVP doesn't need to scrape at all. Download → filter → score → report. Daily runtime drops from 30 min to 30 seconds.

**For your profile specifically:**
- 10,278 BI/Data/Analytics jobs in the dataset right now
- 78 in Arizona
- 1,420 remote
- Mid/Senior level: 9,552

### Finding 2: Full Scrape Takes 25-35 Minutes, Not 5-10
**Measured (real API calls from your machine):**
| Platform | Sample | Time | Estimated Full |
|----------|--------|------|----------------|
| Greenhouse | 50/4,516 | 8.4s | ~4 min (30 workers) |
| Lever | 50/947 | 15.1s | ~5 min |
| Ashby | 50/798 | 1.8s | ~0.5 min |
| BambooHR | 30/2,519 | 2.2s | ~3 min |
| Workday | 20/3,493 | 6.7s (page 1 only) | ~20 min (with pagination + delays) |
| **Total** | | | **~33 min** |

Workday is the bottleneck — 3,493 companies with pagination and mandatory delays between pages. JBA's GitHub Action has a 3-hour timeout for this reason.

### Finding 3: awesome-easy-apply Provides Company Metadata
**Parsed:** 791 companies with name, description, headquarters location, LinkedIn URL, career page URL.
- 540 Greenhouse slugs, 251 Lever slugs
- **149 Greenhouse + 171 Lever slugs NOT in JBA seed data** — bonus companies we can add
- Company descriptions useful for industry matching

### Finding 4: Python 3.9 Has SSL Issues
System Python 3.9.6 throws `urllib3 v2 only supports OpenSSL 1.1.1+` warnings. Using Python 3.13 in a venv.

### Finding 5: Big Tech Workday Gaps
Google, Apple, Amazon, Microsoft, Meta, Microchip are NOT in JBA's Workday seed data. NVIDIA and Intel ARE there. These companies primarily use their own career sites or Greenhouse.

However, JBA's download data DOES include their jobs if they're scraped from other ATS platforms (e.g., Google Fiber on Greenhouse).

### Finding 6: Lever is Flaky
Netflix Lever API timed out at both 10s and 30s. Other Lever companies worked fine. Need robust timeout/retry handling.

### Finding 7: No Workable Company List
JBA has the Workable fetcher but no seed data file for Workable companies. Dead code unless we discover Workable companies ourselves (Phase 3 via CF Crawl or manual).

---

## Decision Log

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Scoring level | **Job-level, NOT company-level** | Can't predict which companies have relevant jobs |
| 2 | Data source (MVP) | **Download JBA + live scrape preferred** | 502K jobs in 15s + fresh data for targets |
| 3 | Orchestration | **Claude via SKILL.md** | Full skill experience, Claude runs Python |
| 4 | Python | **3.13 in venv** | Latest, no SSL issues |
| 5 | Output | **CSV + terminal summary** (Excel in Phase 2) | Minimal deps for MVP |
| 6 | Profile input | **YAML config** (not CLI questionnaire) | Simpler, editable |
| 7 | Data storage | **Local JSON files** | No DB needed |
| 8 | Dedup | **JBA's URL-based get_dedup_key + composite fallback** | Primary: battle-tested URL key. Fallback: (ats, slug, job_id) catches URL format drift |
| 9 | awesome-easy-apply | **Merge slugs into seed data, skip description-based scoring** | 320 bonus slugs valuable; descriptions only cover 9.8% of companies |
| 10 | Stale data | **30-day TTL from JBA's merge_data.py** | Prevents accumulating dead listings |
| 11 | Resume engine | **Phase 2** | Get job discovery working first |
| 12 | LinkedIn scraping | **Phase 2** | G-Stack integration validated, cookies working |
| 13 | CF Crawl | **Phase 3** | Only needed for non-ATS companies |
| 14 | Live scrape scope | **Preferred companies only** | <100 companies, ~2-5 min, fresh data where it matters |
| 15 | JBA download method | **Dynamic discovery via repo tree API + manifest** | Self-healing when JBA changes chunk count/names |
| 16 | Vendoring strategy | **Vendor with SHA marker + update script + weekly staleness check** | Full control to customize; Tier 1 fallback mitigates drift risk |
| 17 | Profile loading | **Shared src/config.py** | DRY — avoids duplicating load_profile() across 3 files |
| 18 | Scrape failure handling | **Best-effort merge + structured failure report** | Claude presents what failed; user knows what's missing |
| 19 | Company scoring | **Binary (preferred=1.0, else=0.0)** | 3-tier scoring not worth it at 9.8% metadata coverage |
| 20 | Calibration | **Auto-generated from profile.yaml (Level 2)** | Portable regression tests; interactive feedback (Level 3) in Phase 2H |
| 21 | Test organization | **tests/unit/ + tests/integration/ + tests/fixtures/** | Fast unit tests (<1s) separated from slow API tests |
| 22 | Download workers | **10 workers (ThreadPoolExecutor)** | 20 chunks / 10 workers = fast; GitHub handles it fine |
| 23 | Scoring scope | **Score all 502K jobs** | 3-5s + 250MB acceptable; no false negatives from pre-filtering |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  JOBHUNTER AI — HYBRID ARCHITECTURE                                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  TIER 1: JBA DOWNLOAD (502K jobs, ~15 seconds)                     │  │
│  │                                                                     │  │
│  │  src/downloader.py                                                  │  │
│  │    → Download 21 gzipped chunks from GitHub raw URLs               │  │
│  │    → Parallel download with ThreadPoolExecutor                     │  │
│  │    → Decompress + merge → data/jba/YYYY-MM-DD.json                │  │
│  │    → Cache: skip if already downloaded today                       │  │
│  │    → Covers: Greenhouse (4,516), Lever (947), Workday (3,493),    │  │
│  │             Ashby (798), BambooHR (2,519) = 12,273 companies      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  TIER 2: LIVE SCRAPE (preferred companies, ~2-5 min)               │  │
│  │                                                                     │  │
│  │  src/jba_fetcher.py (vendored from JBA, MIT)                       │  │
│  │    → Scrape ONLY preferred companies for freshest data             │  │
│  │    → ~50-100 companies from config/profile.yaml                   │  │
│  │    → 6 ATS fetchers: Greenhouse, Lever, Workday, Ashby,           │  │
│  │      BambooHR, Workable                                            │  │
│  │    → ThreadPoolExecutor: 30 workers (10 for BambooHR)             │  │
│  │    → Live results override stale JBA download data                │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  PROCESSING PIPELINE                                                │  │
│  │                                                                     │  │
│  │  src/scraper.py (orchestrator)                                      │  │
│  │    1. Download JBA data (if not cached today)                      │  │
│  │    2. Live scrape preferred companies                              │  │
│  │    3. Merge: live data wins on duplicates (get_dedup_key)          │  │
│  │    4. Clean: remove invalid jobs (clean_job_data)                  │  │
│  │    5. Prune: drop jobs > 30 days old                              │  │
│  │    6. Save: data/jobs/YYYY-MM-DD.json                             │  │
│  │                                                                     │  │
│  │  src/matcher.py (job-level scoring)                                 │  │
│  │    1. Load profile from config/profile.yaml                        │  │
│  │    2. Filter: exclude interns, exclude recruiters                  │  │
│  │    3. Score: title_match, location, level, keywords, company_pref │  │
│  │    4. Rank: P1/P2/P3/P4                                           │  │
│  │    5. Save: data/scored/YYYY-MM-DD.json                           │  │
│  │                                                                     │  │
│  │  src/report.py (output)                                             │  │
│  │    1. CSV: data/reports/YYYY-MM-DD.csv                             │  │
│  │    2. Terminal summary for Claude to present                       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  CLAUDE ORCHESTRATION (SKILL.md)                                    │  │
│  │                                                                     │  │
│  │  User: "Find me jobs"                                               │  │
│  │    → Claude activates venv                                         │  │
│  │    → Claude runs: python src/scraper.py                            │  │
│  │    → Claude runs: python src/matcher.py                            │  │
│  │    → Claude runs: python src/report.py                             │  │
│  │    → Claude reads report, presents summary:                        │  │
│  │      "Found 10,278 BI/Analytics jobs. 42 are P1 matches.          │  │
│  │       Top: Anthropic - Analytics Data Engineer (Score: 95)         │  │
│  │       14 new since yesterday. Report saved."                       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
job-finder/
├── SKILL.md                          # Claude skill definition
├── PLAN.md                           # This document
├── TODOS.md                          # Phase tracking
├── README.md                         # GitHub README
├── LICENSE                           # MIT
├── .gitignore
├── .env                              # Secrets (gitignored)
├── .env.example
├── requirements.txt                  # requests, pyyaml
├── aditya_resume.tex                 # Reference (existing)
│
├── config/
│   ├── profile.yaml                  # User profile + preferences + preferred companies
│   └── profile.yaml.example          # Template for other users
│
├── data/
│   ├── seed/                         # COMMITTED — company slugs
│   │   ├── greenhouse.json           # 4,516 + 149 from awesome-easy-apply = 4,665
│   │   ├── lever.json                # 947 + 171 from awesome-easy-apply = 1,118
│   │   ├── workday.json              # 3,493
│   │   ├── ashby.json                # 798
│   │   ├── bamboohr.json             # 2,519
│   │   └── company_meta.json         # 791 companies with descriptions from awesome-easy-apply
│   ├── jba/                          # GITIGNORED — downloaded JBA data (cached daily)
│   ├── jobs/                         # GITIGNORED — merged job data per day
│   ├── scored/                       # GITIGNORED — scored results per day
│   └── reports/                      # GITIGNORED — CSV reports per day
│
├── src/
│   ├── __init__.py
│   ├── downloader.py                 # Download JBA pre-scraped data from GitHub
│   ├── jba_fetcher.py                # VENDORED from JBA (MIT) — 6 ATS fetchers for live scraping
│   ├── scraper.py                    # Orchestrator: download + live scrape + merge + clean
│   ├── matcher.py                    # Job-level scoring + ranking
│   └── report.py                     # CSV generation + terminal summary
│
└── tests/
    ├── __init__.py
    ├── test_downloader.py
    ├── test_jba_fetcher.py
    ├── test_matcher.py
    └── test_report.py
```

---

## Profile Config (config/profile.yaml)

```yaml
name: "Aditya Mujumdar"
email: "adityamujumdar09@gmail.com"
location: "Chandler, AZ"
willing_to_relocate: true
relocation_cities:
  - "San Francisco, CA"
  - "Seattle, WA"
  - "New York, NY"
  - "Austin, TX"
  - "Denver, CO"
remote_ok: true

years_experience: 5
target_level: "mid"         # mid or senior
exclude_levels: ["intern"]

target_roles:
  - "Business Intelligence"
  - "BI Developer"
  - "BI Engineer"
  - "BI Analyst"
  - "Data Analyst"
  - "Business Analyst"
  - "Analytics Engineer"
  - "Data Engineer"
  - "Analytics Manager"
  - "Business Intelligence Manager"

skills:
  - Python
  - SQL
  - Tableau
  - Power BI
  - Azure
  - R
  - VBA
  - Oracle SQL
  - SPSS
  - Google Analytics
  - Adobe Analytics
  - Kibana
  - ETL
  - Machine Learning
  - Financial Modeling

# Keywords that boost a job's score when found in title
boost_keywords:
  - "analytics"
  - "intelligence"
  - "reporting"
  - "dashboard"
  - "visualization"
  - "data"
  - "insights"
  - "forecast"

# Companies to live-scrape for freshest data
# Format: slug (for known ATS) or name (for discovery)
preferred_companies:
  greenhouse:
    - "anthropic"
    - "figma"
    - "stripe"
    - "notion"
    - "databricks"
    - "snowflakecomputing"
    - "plaid"
    - "brex"
    - "ramp"
    - "relativityspace"
  lever:
    - "netflix"
    - "twitch"
  workday:
    - "nvidia|wd5|NVIDIAExternalCareerSite"
    - "intel|wd1|External"
  ashby:
    - "1password"
    - "linear"

exclude_recruiters: true
exclude_staffing: true
```

---

## Match Scoring Algorithm (Job-Level)

```
MATCH_SCORE(job, profile) → float [0, 100]

PRE-FILTERS (binary exclude):
  ✗ job.skill_level in profile.exclude_levels → SKIP
  ✗ job.is_recruiter AND profile.exclude_recruiters → SKIP
  ✗ job.title contains "intern" AND profile.target_level != "intern" → SKIP

SCORING WEIGHTS:
  title_match:        0.35  ← Best fuzzy match of job.title vs profile.target_roles
                              "Data Analyst" vs "Data Analyst" = 1.0
                              "Sr. BI Engineer" vs "BI Engineer" = 0.9
                              "Software Engineer" vs "Data Analyst" = 0.1
                              Uses token overlap: |intersection| / |union| of title words
                              
  location_match:     0.20  ← Scoring:
                              exact_city (Chandler, AZ) = 1.0
                              same_metro (Phoenix, Tempe, Scottsdale) = 0.95
                              same_state (AZ) = 0.8
                              relocation_city = 0.7
                              "Remote" = 1.0 (if remote_ok)
                              other = 0.2
                              
  level_match:        0.15  ← job.skill_level == profile.target_level = 1.0
                              one level off (mid target, senior job) = 0.7
                              two levels off = 0.3
                              
  keyword_boost:      0.15  ← Count of profile.boost_keywords found in job.title
                              normalized: min(matches / 2, 1.0)
                              
  company_preference: 0.10  ← In preferred_companies = 1.0
                              Not preferred = 0.0
                              NOTE: Simplified to binary (eng review Decision 10).
                              awesome-easy-apply covers only 9.8% of 8,036 JBA companies.
                              3-tier scoring (preferred/metadata/unknown) deferred to Phase 2
                              when company metadata coverage improves.
                              
  recency:            0.05  ← max(0, 1 - days_since_scraped / 30)

FINAL SCORE = sum(weight * factor) * 100

PRIORITY TIERS:
  P1 (85-100): Apply immediately — strong title + location + level match
  P2 (70-84):  Strong match — worth applying this week
  P3 (50-69):  Partial match — apply if time permits
  P4 (<50):    Weak match — saved for reference
```

---

## Build Order — Phase 1 (MVP)

```
Step 1: Environment Setup (~20 min)
  ├── Create Python 3.13 venv
  ├── Install requirements (requests, pyyaml, pytest)
  ├── Update .gitignore
  ├── Create directory structure (data/seed, data/jba, data/jobs, data/scored, data/reports)
  ├── Create src/config.py (shared load_profile, constants, dir paths, date format)
  ├── Create test directory structure:
  │   ├── tests/conftest.py (generate_calibration_jobs from profile, shared fixtures)
  │   ├── tests/unit/
  │   ├── tests/integration/
  │   └── tests/fixtures/ (auto-generated, gitignored)
  ├── config/profile.yaml (Aditya's real profile from resume)
  ├── config/profile.yaml.example
  └── TEST: venv activates, imports work, pytest discovers test dirs

Step 2: Seed Data (~30 min)
  ├── Copy JBA seed data → data/seed/ (greenhouse, lever, workday, ashby, bamboohr)
  ├── Merge awesome-easy-apply slugs into seed (149 GH + 171 Lever bonus)
  ├── Parse awesome-easy-apply → data/seed/company_meta.json (791 companies with descriptions)
  └── TEST: All JSON files load, counts match expected

Step 3: Downloader (~45 min)
  ├── src/downloader.py
  │   ├── download_jba_data(cache_dir) → downloads all chunks from GitHub
  │   ├── Dynamic discovery: fetch GitHub repo tree API to find manifest URL
  │   ├── Download jobs_manifest.json first, then download listed chunks
  │   ├── Parallel chunk download (ThreadPoolExecutor, 10 workers)
  │   ├── Chunk-level validation: skip corrupt gzip or invalid JSON, log warning
  │   ├── Validation gate: assert total > 100K jobs (catch silent failures)
  │   ├── Cache: skip if data/jba/YYYY-MM-DD.json exists
  │   ├── Fallback: if download fails, use yesterday's cached data (warn user)
  │   ├── Decompress + merge all valid chunks → single list
  │   ├── Return: list of job dicts
  │   └── CLI: python src/downloader.py [--force]
  ├── TEST (unit): Cache hit skips download
  ├── TEST (unit): Partial chunk failure → skip bad chunks, continue
  ├── TEST (unit): Validation gate fails (<100K) → fallback to cache
  ├── TEST (integration): Download runs, returns 500K+ jobs
  └── TEST (integration): Job format has required fields (title, company, location, url, ats)

Step 4: Vendor JBA Fetcher (~45 min)
  ├── src/jba_fetcher.py (from JBA scripts/scraper.py)
  │   ├── KEEP: All 6 fetch_company_jobs_* functions
  │   ├── KEEP: fetch_all_jobs(), job_tier_classification(), is_recruiter_company()
  │   ├── KEEP: clean_job_data(), USER_AGENTS, RECRUITER_TERMS
  │   ├── ADD: get_dedup_key() from merge_data.py
  │   ├── ADD: get_composite_key(job) → (ats, slug, job_id) fallback dedup
  │   ├── REMOVE: save_results(), main(), argparse, OUTPUT_DIR, file paths
  │   ├── CHANGE: load_companies() → accept list param instead of file path
  │   ├── Header: "Vendored from github.com/Feashliaa/job-board-aggregator (MIT)"
  │   └── Header: "Pinned SHA: <commit_hash> — run scripts/update_vendor.sh to check for updates"
  ├── scripts/update_vendor.sh
  │   ├── Clone JBA at latest, diff against vendored jba_fetcher.py
  │   ├── Show only changes to functions we use
  │   └── Weekly staleness check in scraper.py: compare pinned SHA vs latest via GitHub API
  ├── TEST (unit): job_tier_classification("Senior Data Engineer") → "senior"
  ├── TEST (unit): is_recruiter_company("staffingsolutions") → True
  ├── TEST (unit): get_dedup_key() URL-based + Workday composite
  ├── TEST (unit): get_composite_key() catches URL-mismatch duplicates
  ├── TEST (integration): fetch_company_jobs_greenhouse("anthropic") returns 450+ jobs
  └── TEST (integration): fetch_company_jobs_ashby("1password") returns 60+ jobs

Step 5: Scraper Orchestrator (~1 hr)
  ├── src/scraper.py
  │   ├── Uses config.load_profile() (shared, not duplicated)
  │   ├── load_seed_data(seed_dir) → dict of {platform: [slugs]}
  │   ├── scrape_preferred(profile, seed_data) → (jobs, scrape_report)
  │   │   ├── Read preferred_companies from profile
  │   │   ├── Call jba_fetcher per platform
  │   │   ├── ~2-5 min for ~50-100 companies
  │   │   └── Returns scrape_report: {succeeded: [...], failed: [{slug, platform, error}]}
  │   ├── merge_jobs(jba_jobs, live_jobs) → deduplicated list
  │   │   ├── Primary dedup: get_dedup_key (URL-based, Workday composite)
  │   │   ├── Fallback dedup: get_composite_key (ats, slug, job_id)
  │   │   ├── Live data wins on duplicates
  │   │   ├── Log: "X jobs overridden by live data" (monitor dedup health)
  │   │   └── Prune jobs > 30 days old
  │   ├── Weekly vendor staleness check: compare pinned JBA SHA vs latest
  │   ├── Save to data/jobs/YYYY-MM-DD.json
  │   └── CLI: python src/scraper.py [--skip-download] [--skip-live] [--live-only]
  ├── TEST (unit): Dedup — live wins on duplicates
  ├── TEST (unit): Dedup — composite key catches URL-mismatch
  ├── TEST (unit): Stale job pruning (>30 days)
  ├── TEST (unit): Partial scrape failure → best-effort + report
  ├── TEST (integration): Full run produces data/jobs/YYYY-MM-DD.json
  └── TEST (integration): --skip-live produces download-only results

Step 6: Matcher (~1 hr)
  ├── src/matcher.py
  │   ├── Uses config.load_profile() (shared, not duplicated)
  │   ├── score_job(job, profile) → float [0, 100]
  │   │   ├── title_match (0.35): token overlap with target_roles
  │   │   ├── location_match (0.20): city/state/remote detection
  │   │   ├── level_match (0.15): skill_level vs target_level
  │   │   ├── keyword_boost (0.15): boost_keywords in title
  │   │   ├── company_preference (0.10): binary — preferred=1.0, else=0.0
  │   │   └── recency (0.05): days since scraped_at
  │   ├── Edge case defaults: missing title→0, missing location→0.2,
  │   │   missing level→0.5, missing scraped_at→0.5, missing company→0.0
  │   ├── classify_priority(score) → "P1"/"P2"/"P3"/"P4"
  │   ├── Filter: exclude_levels, exclude_recruiters
  │   ├── Rank by score descending
  │   ├── Save to data/scored/YYYY-MM-DD.json
  │   └── CLI: python src/matcher.py [--date YYYY-MM-DD] [--min-score 50]
  ├── TEST (unit, calibration): Auto-generated P1 jobs from profile score ≥85
  ├── TEST (unit, calibration): Auto-generated P4 jobs from profile score <50
  ├── TEST (unit): Pre-filter excludes interns
  ├── TEST (unit): Pre-filter excludes recruiters
  ├── TEST (unit): Remote jobs → location_match = 1.0
  ├── TEST (unit): Missing fields handled gracefully (defaults applied)
  └── TEST (unit): Preferred company → company_preference = 1.0

Step 7: Report (~30 min)
  ├── src/report.py
  │   ├── Load scored jobs from data/scored/YYYY-MM-DD.json
  │   ├── Generate CSV: priority, score, title, company, location, url, ats, level
  │   ├── Sort: P1 first, then by score desc
  │   ├── Print terminal summary (for Claude to read):
  │   │   ├── "Found X matching jobs (Y total scanned)"
  │   │   ├── "P1: X jobs, P2: Y jobs, P3: Z jobs"
  │   │   ├── "Top 10 P1 matches:" with titles/companies/scores
  │   │   └── Stats: platforms, locations, levels
  │   ├── Save to data/reports/YYYY-MM-DD.csv
  │   └── CLI: python src/report.py [--date YYYY-MM-DD] [--top N]
  ├── TEST: CSV generates with correct columns
  └── TEST: Terminal summary is readable

Step 8: SKILL.md (~30 min)
  ├── Skill definition for Claude
  ├── Commands: "find jobs", "show report", "update profile"
  ├── Pipeline invocation sequence
  ├── How Claude should interpret and present results
  └── TEST: Claude can run full pipeline via skill

Step 9: End-to-End Test (~30 min)
  ├── Run full pipeline: scraper → matcher → report
  ├── Review P1 results: Are they actually good matches?
  ├── Tune scoring weights based on results
  ├── Measure total runtime
  └── Validate: CSV opens correctly, data makes sense
```

**Total Phase 1: ~6-7 hours of focused work.**
**Daily runtime: ~3-6 minutes** (15s download + 2-5 min live scrape + <1s scoring + <1s report)

---

## Phase 2 (After MVP Works)

```
2A. "New Today" Diffing (~30 min)
    ├── Compare today vs yesterday: ⭐ new, ❌ gone
    └── "5 new P1 jobs today! 2 from yesterday no longer listed."

2B. Excel Reports (~1 hr)
    ├── openpyxl: colored rows by priority, auto-column-width
    └── Multiple sheets: P1 jobs, all jobs, stats

2C. Application Status Tracker (~2 hr)
    ├── JSON-backed CRM: Not Applied → Applied → Phone Screen → Interview → Offer
    └── Claude prompts: "You applied to X 5 days ago. Any updates?"

2D. LinkedIn Job Search via G-Stack (~3 hr)
    ├── Cookie auth check recipe
    │   ├── VALIDATED: G-Stack + Brave cookies work for LinkedIn (eng review session)
    │   ├── GOTCHA: li_at cookie is on .www.linkedin.com, not .linkedin.com
    │   ├── Must import BOTH domains: .linkedin.com AND .www.linkedin.com
    │   ├── Brave must be quit before cookie import (macOS Keychain lock)
    │   ├── Pre-scrape validation: navigate to linkedin.com/feed, check for login page
    │   └── If expired: prompt user to re-import via cookie-import-browser
    ├── Job search with block detection
    └── Merges with ATS data

2E. LinkedIn Connection Mapper (~2 hr)
    ├── Scrape connections → cross-ref with jobs
    └── 🤝 badges: "You know Jane at Anthropic"

2F. Skill Gap Analysis (~30 min)
    ├── Match profile.skills against job title/department keywords
    └── "✅ Python, SQL, Tableau | ❌ Missing: Spark, dbt"

2G. Resume Engine (~4 hr)
    ├── LaTeX template + tailoring per job
    └── Weasyprint fallback

2H. Interactive Scoring Calibration (~2 hr)
    ├── After pipeline run, Claude presents top 5 + bottom 5 scored jobs
    ├── User rates each: ✅ Would apply / ❌ Skip / 🤷 Maybe
    ├── Saves feedback to data/calibration/feedback.json
    ├── On subsequent runs, validate scores against feedback
    ├── If a "would apply" job scores P3 → flag weight miscalibration
    └── Complements Level 2 auto-gen calibration (MVP) with real-world ground truth
```

---

## Phase 3 (Nice-to-Have)

```
3A. CF Crawl for Career URL Discovery
3B. Generic Career Page Scraping (G-Stack)
3C. Referral Message Drafter
3D. Salary Intelligence (Levels.fyi scraping)
3E. Job Market Trend Analytics (matplotlib)
3F. Seed Data Auto-Update Script
3G. Cover Letter Generator
3H. Workable Company Discovery
```

---

## Data Flow Diagram

```
                    ┌─────────────────────┐
                    │  GitHub (JBA repo)   │
                    │  502K jobs, daily    │
                    └────────┬────────────┘
                             │ download (15s)
                             ▼
┌──────────────┐    ┌─────────────────────┐    ┌──────────────┐
│  Preferred   │    │                     │    │ company_meta │
│  Companies   │───▶│   src/scraper.py    │◀───│  .json       │
│  (live API)  │    │   (orchestrator)    │    │ (791 co's)   │
│  ~2-5 min    │    │                     │    └──────────────┘
└──────────────┘    └────────┬────────────┘
                             │ merge + dedup + clean
                             ▼
                    ┌─────────────────────┐
                    │  data/jobs/         │
                    │  YYYY-MM-DD.json    │
                    │  ~500K jobs         │
                    └────────┬────────────┘
                             │ score each job vs profile
                             ▼
                    ┌─────────────────────┐
                    │  src/matcher.py     │◀── config/profile.yaml
                    │  title, location,   │
                    │  level, keywords,   │
                    │  company pref       │
                    └────────┬────────────┘
                             │ filter + rank
                             ▼
                    ┌─────────────────────┐
                    │  data/scored/       │
                    │  P1: ~30-50 jobs    │
                    │  P2: ~100-200 jobs  │
                    │  P3: ~500+ jobs     │
                    └────────┬────────────┘
                             │ format
                             ▼
                    ┌─────────────────────┐
                    │  CSV Report +       │
                    │  Terminal Summary   │
                    │  (Claude presents)  │
                    └─────────────────────┘
```

---

## Error Handling

```
DOWNLOADER:
  GitHub rate limit        → Retry after 60s, max 3 retries
  Network timeout          → Retry, fallback to cached data
  Corrupt gzip             → Skip chunk, log warning
  No internet              → Use yesterday's cached data (warn user)

JBA FETCHER (live scrape):
  HTTP 404                 → Skip company (slug may be stale)
  Network timeout          → Skip after 30s (JBA default)
  Lever timeout            → Retry once with 60s timeout (Lever is slow)
  Workday silent blocking  → Detect via total mismatch, stop pagination
  Thread crash             → Caught by future.result(), continue

MATCHER:
  Missing job fields       → Score 0 for that factor, don't crash
  Invalid scraped_at date  → Treat recency as 0.5

REPORT:
  0 matching jobs          → "No matching jobs found" + empty CSV
  0 P1 jobs                → Still show P2-P4 results
```

---

## NOT in Scope (Ever)

| Item | Rationale |
|---|---|
| Auto-submit applications | Legal/ethical — draft only |
| ~~Web UI~~ | ~~CLI/terminal-native, Claude skill~~ → Now: Static HTML dashboard on GitHub Pages |
| Multi-user | Profile-based — fork and customize |
| Full JBA repo fork | Vendor fetcher + download data only |
| Company-level scoring | Wrong approach — score at job level |
| Mobile app | CLI |

---

## Runtime Estimates (Daily)

```
COMPONENT                    TIME        NOTES
─────────────────────────────────────────────────────────────
Download JBA data            ~15s        21 chunks, 17MB, cached daily
Live scrape preferred        ~2-5 min    50-100 companies across 4-6 ATS
Merge + dedup + clean        ~2s         CPU-only on local JSON
Score 500K jobs              ~3-5s       CPU-only, simple math per job
Filter + rank                <1s         Sort + classify
Generate CSV                 <1s         Write file
─────────────────────────────────────────────────────────────
TOTAL                        ~3-6 min    Down from 33+ min full scrape
```

---

## Aditya's Profile Summary (from resume)

- **Current role:** Business Intelligence - Marketing at Microchip Technology (Oct 2020 - Present, ~5 years)
- **Location:** Chandler, AZ (metro Phoenix)
- **Core skills:** Python, SQL, R, VBA, Bash, Tableau, Power BI, Azure, Oracle SQL
- **Strengths:** Financial modeling, ML models, BI dashboards, marketing analytics, ETL, data engineering
- **Education:** BSE Computer Systems Engineering + Applied Business Data Analytics Certificate, ASU
- **Target:** Mid-to-senior BI/Analytics roles, open to relocation and remote
