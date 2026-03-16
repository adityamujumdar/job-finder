# TODOS — JobHunter AI

## Phase 1 — MVP (Hybrid: Download + Live Scrape) ✅ COMPLETE

- [x] **Step 1:** Environment — Python 3.13 venv, requirements.txt, .gitignore, dirs, profile.yaml
  - [x] Create `src/config.py` — shared `load_profile()`, constants, profile validation
  - [x] Create test directory structure: `tests/unit/`, `tests/integration/`, `tests/conftest.py`
- [x] **Step 2:** Seed data — JBA seeds (12,273 companies) + awesome-easy-apply slugs (+320 = 149 GH + 171 Lever). company_meta.json (791 companies)
- [x] **Step 3:** Downloader — src/downloader.py
  - [x] Dynamic discovery via GitHub repo tree API
  - [x] Download jobs_manifest.json first, then listed chunks
  - [x] Parallel chunk download: 10 workers, 1.3s for 502K jobs
  - [x] Chunk-level validation + validation gate (>100K)
  - [x] Fallback to yesterday's cache on failure
- [x] **Step 4:** Vendor JBA fetcher — src/jba_fetcher.py (6 ATS fetchers, pinned SHA d6f4af0)
  - [x] get_dedup_key() from merge_data.py + get_composite_key() fallback
  - [x] scripts/update_vendor.sh for staleness checking
- [x] **Step 5:** Scraper orchestrator — src/scraper.py (download → live → merge → clean → prune → save)
  - [x] Dual dedup: primary URL-based + composite fallback
  - [x] Weekly vendor staleness check
- [x] **Step 6:** Matcher — src/matcher.py (score all 502K jobs in 11s)
  - [x] Title: containment + Jaccard hybrid scoring
  - [x] Location: word-boundary state matching (fixed "ca" in "Chicago" bug)
  - [x] Calibration: P1 fixtures score ≥85, P4 fixtures score <50
  - [x] Edge case defaults for all missing fields
- [x] **Step 7:** Report — src/report.py (CSV + terminal summary)
- [x] **Step 8:** SKILL.md — Claude skill definition
- [x] **Step 9:** End-to-end test — full pipeline validated
  - [x] 502,747 jobs → 51 P1, 1,188 P2, 6,976 P3
  - [x] Top P1: Netflix Analytics Engineer (97.9), Anthropic Analytics Data Engineer (92.8)
  - [x] 79/79 unit tests passing in 0.69s
  - [x] Total pipeline: ~15s (download-only) or ~3-5 min (with live scrape)

## Phase 1.5 — Critical Fixes ✅ COMPLETE

- [x] **BUG-3/4:** Matcher outputs only P1-P3 (162MB→1.5MB scored) ✅
- [x] **BUG-2:** Fix Netflix: moved from `lever` to `workday` in profile.yaml ✅
- [x] **BUG-6:** Fix `relataboratories` typo in PLAN.md ✅
- [x] **BUG-7:** CRITICAL — Fix title scoring false positives ✅
  - Replaced token-bag containment with phrase-level matching
  - "Data Center Controls Engineer" went from 0.95 → 0.15
  - "Software Engineer, Data Infrastructure" went from 0.95 → 0.15
  - BI/analytics titles unaffected (still 0.96-1.0)
  - Added SWE-family word detection to penalize wrong job families
  - Zero false positives in P1 (verified)
- [x] **BUG-8:** Re-run full pipeline with 502K jobs (was only 2,297) ✅
- [x] **BUG-9:** Add company blocklist — removed staffing farms ✅
  - jobgether (19K), launch2 (1.5K), globalhr (5K), ghr (4.5K), svetness, tsmg, pae
- [x] **ARCH-2:** Write README.md ✅
- [x] **Static HTML dashboard** — Tailwind CSS, search, filters, dark mode ✅
- [x] **GitHub Actions workflow** — daily cron @ 8am UTC ✅
- [x] **MIT License + Attribution** ✅

## Phase 1.5 — Remaining Fixes

- [ ] **WASTE-4:** Cache JBA download as gzip (154MB→17MB)
- [ ] **WASTE-1:** Add `scripts/cleanup.sh` — rotate data older than 7 days
- [ ] **BUG-1:** Add pipeline state validation (matcher checks jobs file freshness)

## Phase 2 — Product Layer

### 2.0 — Claude Intelligence Layer (SKILL.md)
- [x] **Conversational profile setup** — Claude asks questions, generates profile.yaml ✅ (in SKILL.md)
- [x] **Natural language filters** — "show me remote BI roles at FAANG" ✅ (in SKILL.md)
- [x] **Resume tailoring workflow** — read job, tailor resume .tex ✅ (in SKILL.md)
- [ ] **LLM-based job classification** — Claude Haiku scores top 5K candidates for precision
- [ ] **Job analysis** — "tell me about this job" → skill match, honest assessment

### 2.1 — LinkedIn Integration
- [ ] **Import Brave cookies** via G-Stack `cookie-import-browser brave`
- [ ] **LinkedIn job search scraper** — search by keywords, paginate results
- [ ] **Merge LinkedIn jobs** into pipeline (ats: "linkedin", dedup vs JBA)
- [ ] **Connection cross-reference** — "You know Jane at Anthropic" 🤝

### 2.2 — Resume Engine
- [ ] **`src/resume_engine.py`** — programmatic LaTeX tailoring per job
- [ ] **Skill gap analysis** per job (✅/❌ per requirement)
- [ ] **Cover letter generation** (optional, Claude-powered)
- [ ] **Apply workflow in dashboard** — click → tailored resume → open job page

### 2.x — Web Features
- [ ] **"New Today" diffing** — ⭐ new, ❌ gone (compare vs yesterday)
- [ ] **Application tracker** — localStorage-based Applied/Skipped/Saved per job
- [ ] **Profile onboarding page** — web form → profile.yaml
- [ ] **Daily email digest** — optional HTML email with P1 matches

### 2.x — Scoring Improvements
- [ ] **2F:** Skill gap analysis (✅/❌ per job)
- [ ] **2H:** Interactive scoring calibration
- [ ] **Fix:** company metadata coverage (9.8% → enable 3-tier scoring)

## Phase 3 — Nice-to-Have

- [ ] **3B:** Generic career page scraping (G-Stack)
- [ ] **3C:** Referral message drafter
- [ ] **3E:** Job market trend analytics
- [ ] **3F:** Seed data auto-update script
- [ ] **3H:** Workable company discovery

## Killed Items

- ~~company_db.py~~ — Score at job level, not company level
- ~~intake.py~~ — YAML config is simpler
- ~~Full self-scrape as primary~~ — Download JBA's 502K instead
- ~~3-tier company scoring~~ — Only 9.8% metadata coverage
- ~~Pre-filtering before scoring~~ — 11s for 502K is fine (revisit if disk matters)
- ~~Excel reports (2B)~~ — Static HTML dashboard replaces this
- ~~Cover letter generator (3G)~~ — Claude already does this on demand via SKILL.md
- ~~CF Crawl (3A)~~ — 502K jobs is already massive coverage
- ~~Salary intelligence (3D)~~ — Nice-to-have, not core
- ~~Streamlit~~ — Can't run on GitHub Pages, static HTML is cheaper and better
- ~~Flask web app~~ — Static site with JS is sufficient, no server costs

## Key Metrics

- [x] P1 accuracy: Zero false positives, Netflix/Anthropic/Stripe analytics roles ✅
- [x] P1+P2 coverage: 1,239 jobs across 673 companies ✅
- [x] Runtime: 15s download + 11s scoring = 26s total ✅
- [x] Tests: 79/79 unit tests, 0.69s ✅
- [x] Disk: 1.5MB scored (down from 162MB, 99% reduction) ✅
- [ ] Distribution: GitHub Pages dashboard (deploy pending)
- [ ] LinkedIn: Integration pending
- [ ] Resume: Tailoring workflow in SKILL.md, engine pending
