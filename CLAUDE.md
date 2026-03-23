# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JobHunter AI — a Claude skill that automates job discovery across 502K+ jobs from 12K+ companies. Uses a hybrid architecture: downloads pre-scraped data from [job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) (JBA) for bulk coverage (~1.3s), then live-scrapes preferred companies for freshness (~2-5 min).

**Status:** Phase 1 MVP complete. Full pipeline working: download → match → report.

## Architecture (Hybrid Two-Tier)

**Tier 1 — JBA Download:** `src/downloader.py` downloads 21 gzipped JSON chunks from GitHub (502K jobs), caches daily in `data/jba/`.

**Tier 2 — Live Scrape:** `src/jba_fetcher.py` (vendored from JBA, MIT license) scrapes only preferred companies (~50-100) across 6 ATS platforms (Greenhouse, Lever, Workday, Ashby, BambooHR, Workable).

**Pipeline:** `src/scraper.py` (orchestrator) → `src/matcher.py` (job-level scoring) → `src/enricher.py` (fetch descriptions, extract skills/salary) → `src/matcher.py --reblend` (blend enriched scores) → `src/report.py` (CSV + terminal summary) → `src/site_generator.py` (static HTML dashboard for GitHub Pages). Shared config loading via `src/config.py`.

**Onboarding:** `src/resume_parser.py` parses RESUME.md or PDF to auto-generate `config/profile.yaml` — eliminates manual re-typing of skills, location, and target roles.

**Orchestration:** Claude runs the pipeline via SKILL.md skill definition. User says "find me jobs" → Claude runs each step and presents results.

## Commands

```bash
# Environment
source .venv/bin/activate

# Pipeline steps (each is independently runnable)
python -m src.scraper [--skip-download] [--skip-live] [--live-only]
python -m src.matcher [--date YYYY-MM-DD] [--min-score 50]
python -m src.enricher [--date YYYY-MM-DD] [--limit N]  # Fetch descriptions + extract skills
python -m src.matcher --reblend                           # Blend enriched scores into rankings
python -m src.report [--date YYYY-MM-DD] [--top N]
python -m src.site_generator [--date YYYY-MM-DD]          # Generate static HTML dashboard

# Resume → Profile (one-time onboarding)
python -m src.resume_parser [--resume PATH] [--dry-run]   # Auto-generate profile from resume
python -m src.resume_parser --force                        # Overwrite existing profile

# Tests
pytest tests/unit/           # Fast (<1s), 253 tests, no network
pytest tests/integration/    # Slow, requires Playwright installed
pytest                       # All tests

# Dependency validation (catches missing requirements.txt entries)
python scripts/check_deps.py
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

title_match (0.35), location_match (0.20), level_match (0.15), keyword_boost (0.15), company_preference (0.15), recency (0.00). Priority tiers: P1 (85-100), P2 (70-84), P3 (50-69), P4 (<50). Missing fields get safe defaults (not crashes).

## Profile Features

- **`exclude_title_patterns`** — list of title substrings to penalize (e.g., "cloud platform", "devops"). Matching jobs get title_match capped at 0.15 (appear in P3/P4, never P1/P2). Suggested data-driven by `/jobhunter` after pipeline run.
- **`metro_cities`** — list of cities in the user's metro area (e.g., Mississauga, Brampton for Toronto). Gets 0.95 location score. Replaces hardcoded PHOENIX_METRO.
- **Dynamic title penalty words** — `SWE_FAMILY_WORDS` (backend, software, platform, etc.) are automatically removed from the penalty set when they appear in the user's `target_roles`. A Backend SWE profile won't penalize "Software Engineer" titles; a BI profile will.

## Measured Performance (2026-03-15)

- Download: 502,747 jobs in 1.3s (21 chunks, 10 workers)
- Scoring: 477,776 jobs scored in 8.0s (24,971 filtered as interns/recruiters)
- Results: 51 P1, 1,188 P2, 6,976 P3 (zero false positives in P1)
- Live scrape: Anthropic=450 jobs, 1Password=69 jobs (validated)

## Data Layout

- `data/seed/` — **committed** company slugs per ATS platform + company_meta.json (791 companies)
- `data/jba/`, `data/jobs/`, `data/scored/`, `data/reports/` — **gitignored** daily output
- `config/profile.yaml` — user preferences, target roles, preferred companies

## job-finder Skills (Claude Slash Commands)

These skills are available when working in this project (via `.jac/skills/`) and globally after running `./setup`:

| Command | What it does |
|---|---|
| `/jobhunter` | Run the full pipeline: download → match → report → dashboard |
| `/classify-jobs` | Classify scored jobs into APPLY NOW / THIS WEEK / STRETCH / SKIP buckets |
| `/tailor-resume` | Look up a job by ID and generate a tailored HTML/PDF resume |

**When the user types any of these commands (or trigger phrases like "find me jobs",
"classify my jobs", "build a resume for"), read the corresponding SKILL.md file from
the project root and follow its instructions exactly:**

- `/jobhunter` or "find me jobs" → read `jobhunter/SKILL.md`
- `/classify-jobs` or "which jobs should I apply to" → read `classify-jobs/SKILL.md`
- `/tailor-resume` or "build a resume for" → read `tailor-resume/SKILL.md`

**Install globally** (enables these commands in any Claude Code project):
```bash
git clone https://github.com/adityamujumdar/job-finder.git ~/job-finder 2>/dev/null || (cd ~/job-finder && git pull); cd ~/job-finder && ./setup
```

### gstack (Web Browsing, Code Review & Engineering Skills)

JobHunter integrates with [gstack](https://github.com/garrytan/gstack) for two purposes:

1. **Web browsing** (`/browse`) — fetch job descriptions from company career pages not in JBA
2. **Engineering workflows** — `/plan-ceo-review`, `/plan-eng-review`, `/review`, `/ship`, `/retro`, etc.

**Install gstack** (recommended for all users):
```bash
git clone https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup
```

**Always use `/browse` for web browsing — never use `mcp__claude-in-chrome__*` tools.**

#### Browse — Job Description Fetching
Use `/browse` when: a company isn't in JBA, user provides a direct job URL, or user
mentions a specific non-JBA company (Google, Apple, Amazon, Scotiabank, etc.).

```bash
# Setup browse (once per session)
BROWSE_OUTPUT=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)

# Fetch a job description
$B goto <careers_page_url>
$B text
```

**Scoring browsed jobs** — after fetching a job via browse:
```python
from src.matcher import score_and_save_browsed
result = score_and_save_browsed({
    "title": "...", "company": "...", "url": "...",
    "location": "...", "skill_level": "mid",
})
# → scored, classified, appended to data/scored/DATE.json (_source: "browse")
```
Browsed jobs appear in dashboard, CSV report, and `/classify-jobs` alongside JBA jobs.

#### Engineering Skills (from gstack)
These gstack skills work in this project and are recommended for development:

| Skill | When to use |
|---|---|
| `/plan-ceo-review` | Architectural review, high-level design critique |
| `/plan-eng-review` | Technical plan validation, test coverage review |
| `/review` | Pre-landing code review against main branch |
| `/ship` | Automated release: commit, push, deploy |
| `/retro` | Weekly retrospective on shipping patterns |
| `/browse` | Fetch job descriptions from company career pages |
| `/debug` | Systematic debugging of issues |
| `/qa` | Quality assurance testing |

**Full list of gstack skills:** `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`,
`/plan-design-review`, `/design-consultation`, `/review`, `/ship`, `/browse`, `/qa`,
`/qa-only`, `/design-review`, `/setup-browser-cookies`, `/retro`, `/debug`, `/document-release`.

## Critical Rules

1. **Profile staleness check — ALWAYS verify before showing results.**
   Scored data is generated against a specific `config/profile.yaml`. If the profile
   changes after scoring, all results are wrong (a BI analyst's scores mean nothing
   for a Fashion Designer). Before showing scored results, running the report, or
   generating the dashboard:
   ```bash
   python3 -c "
   import json, sys
   from src.config import profile_hash, SCORED_DIR, today
   meta_path = SCORED_DIR / f'{today()}.meta.json'
   if not meta_path.exists():
       print('⚠️  No meta file — rescore needed'); sys.exit(1)
   meta = json.load(open(meta_path))
   current = profile_hash()
   if meta.get('profile_hash') != current:
       print(f'⚠️  Profile changed (was {meta[\"profile_hash\"]}, now {current}) — rescore needed')
       sys.exit(1)
   print(f'✅ Profile: {current}')
   "
   ```
   If the check fails or meta file is missing: run `python -m src.matcher` first.
   **Never show scored results without verifying the profile hash.**

## Enrichment Pipeline

The enricher fetches full job descriptions and extracts skills/salary for scored P1+P2 jobs:

```
scored/DATE.json (P1+P2 jobs)
     │
     ├── incremental skip (enriched within 7 days → skip)
     │
     ├── API jobs (Greenhouse/Lever/Ashby) → ThreadPoolExecutor(8)
     │
     └── Browser jobs (Workday/unknown) → sequential on main thread
         ├── Playwright headless (primary, works in CI)
         └── gstack/browse (fallback, local only)
```

**Important:** Playwright sync API uses greenlets and CANNOT be called from threads.
Browser jobs must run sequentially on the main thread that started the playwright instance.

## LLM Integration (Optional Enhancement)

`src/llm.py` provides optional Claude API integration for tasks where regex/heuristics fall short.
**Requires:** `ANTHROPIC_API_KEY` environment variable. Without it, all functions return None and callers fall back to regex — zero impact on existing pipeline.

```
                    src/llm.py (thin Claude layer)
                    ├── parse_resume()          → resume_parser.py
                    ├── classify_title_match()   → matcher.py (P1+P2 rescore)
                    └── extract_jd_skills()      → enricher.py (P1+P2 only)
```

**What gets upgraded with an API key:**
- **Resume parsing:** LLM extracts name/location/skills/roles from free-form text (handles international formats, non-standard layouts)
- **Title matching:** P1+P2 jobs get semantic title re-scoring (regex handles 502K bulk pass, LLM refines ~1,200 top jobs)
- **Skill extraction:** Section-aware skill classification from job descriptions (required vs nice-to-have)

**Cost model:** ~$1/day using Claude Haiku for full pipeline enhancement.

**Setup:** `export ANTHROPIC_API_KEY=sk-ant-...` or add to `.env` file.

**Override model:** `export JOBHUNTER_LLM_MODEL=claude-sonnet-4-20250514` (default: claude-3-haiku-20240307)

## Known Gotchas

- Lever APIs are flaky (Netflix times out at 30s) — has retry with 60s timeout
- Workday is the scraping bottleneck (3,493 companies with pagination + mandatory delays)
- Big Tech (Google, Apple, Amazon, Microsoft, Meta) are NOT in JBA's Workday seed data
- `.env` contains secrets — never commit
- Netflix is on Workday (not Lever as configured) — JBA download already has their jobs
- **Playwright is NOT thread-safe** — sync API uses greenlets, must run on the same thread that started the instance. This is why browser jobs run sequentially, not in the thread pool.
- **`beautifulsoup4` must be in requirements.txt** — the enricher imports it at module level. CI will break without it. Run `python scripts/check_deps.py` to validate.
- **PyMuPDF is optional** — only needed for PDF resume parsing. Markdown resumes work without it.
