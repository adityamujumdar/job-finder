# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JobHunter AI — a Claude skill that automates job discovery across 502K+ jobs from 12K+ companies. Uses a hybrid architecture: downloads pre-scraped data from [job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) (JBA) for bulk coverage (~1.3s), then live-scrapes preferred companies for freshness (~2-5 min).

**Status:** Phase 1 MVP complete. Full pipeline working: download → match → report.

## Architecture (Hybrid Two-Tier)

**Tier 1 — JBA Download:** `src/downloader.py` downloads 21 gzipped JSON chunks from GitHub (502K jobs), caches daily in `data/jba/`.

**Tier 2 — Live Scrape:** `src/jba_fetcher.py` (vendored from JBA, MIT license) scrapes only preferred companies (~50-100) across 6 ATS platforms (Greenhouse, Lever, Workday, Ashby, BambooHR, Workable).

**Pipeline:** `src/scraper.py` (orchestrator) → `src/matcher.py` (job-level scoring) → `src/report.py` (CSV + terminal summary) → `src/site_generator.py` (static HTML dashboard for GitHub Pages). Shared config loading via `src/config.py`.

**Orchestration:** Claude runs the pipeline via SKILL.md skill definition. User says "find me jobs" → Claude runs each step and presents results.

## Commands

```bash
# Environment
source .venv/bin/activate

# Pipeline steps (each is independently runnable)
python -m src.scraper [--skip-download] [--skip-live] [--live-only]
python -m src.matcher [--date YYYY-MM-DD] [--min-score 50]
python -m src.report [--date YYYY-MM-DD] [--top N]
python -m src.site_generator [--date YYYY-MM-DD]  # Generate static HTML dashboard

# Tests
pytest tests/unit/           # Fast (<1s), 79 tests, no network
pytest tests/integration/    # Slow, hits real APIs
pytest                       # All tests
```

## Key Design Decisions

- **Python 3.13** in venv (system Python 3.9 has SSL issues)
- **Job-level scoring, NOT company-level** — can't predict which companies have relevant jobs
- **Score all 502K jobs** (~8s + 250MB acceptable) — no pre-filtering to avoid false negatives
- **Binary company scoring** (preferred=1.0, else=0.0) — awesome-easy-apply metadata only covers 9.8% of companies
- **Dual dedup:** JBA's URL-based `get_dedup_key` primary + `(ats, slug, job_id)` composite fallback
- **Vendored JBA fetcher** with SHA marker + update script (not git submodule)
- **Profile config in YAML** (`config/profile.yaml`), loaded via shared `src/config.py`
- **Title match uses phrase matching** (v2) — requires contiguous word match, not token bags. "Data Engineer" matches "Senior Data Engineer" but NOT "Data Center Controls Engineer". SWE-family titles are penalized. BI ↔ "Business Intelligence" expansion.
- **Location match uses word boundaries** — prevents "ca" (California) from matching "Chicago"
- **Company blocklist** — staffing farms (jobgether, launch2, globalhr, etc.) excluded alongside is_recruiter filter

## Scoring Weights

title_match (0.35), location_match (0.20), level_match (0.15), keyword_boost (0.15), company_preference (0.10), recency (0.05). Priority tiers: P1 (85-100), P2 (70-84), P3 (50-69), P4 (<50). Missing fields get safe defaults (not crashes).

## Measured Performance (2026-03-15)

- Download: 502,747 jobs in 1.3s (21 chunks, 10 workers)
- Scoring: 477,776 jobs scored in 8.0s (24,971 filtered as interns/recruiters)
- Results: 51 P1, 1,188 P2, 6,976 P3 (zero false positives in P1)
- Live scrape: Anthropic=450 jobs, 1Password=69 jobs (validated)

## Data Layout

- `data/seed/` — **committed** company slugs per ATS platform + company_meta.json (791 companies)
- `data/jba/`, `data/jobs/`, `data/scored/`, `data/reports/` — **gitignored** daily output
- `config/profile.yaml` — user preferences, target roles, preferred companies

## Known Gotchas

- Lever APIs are flaky (Netflix times out at 30s) — has retry with 60s timeout
- Workday is the scraping bottleneck (3,493 companies with pagination + mandatory delays)
- Big Tech (Google, Apple, Amazon, Microsoft, Meta) are NOT in JBA's Workday seed data
- `.env` contains secrets — never commit
- Netflix is on Workday (not Lever as configured) — JBA download already has their jobs
