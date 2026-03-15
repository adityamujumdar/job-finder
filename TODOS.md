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
- [x] **Step 6:** Matcher — src/matcher.py (score all 502K jobs in 8s)
  - [x] Title: containment + Jaccard hybrid scoring
  - [x] Location: word-boundary state matching (fixed "ca" in "Chicago" bug)
  - [x] Calibration: P1 fixtures score ≥85, P4 fixtures score <50
  - [x] Edge case defaults for all missing fields
- [x] **Step 7:** Report — src/report.py (CSV + terminal summary)
- [x] **Step 8:** SKILL.md — Claude skill definition
- [x] **Step 9:** End-to-end test — full pipeline validated
  - [x] 502,747 jobs → 61 P1, 2,215 P2, 10,112 P3
  - [x] Top P1: Netflix Analytics Engineer (97.9), Anthropic Analytics Data Engineer (92.8)
  - [x] 79/79 unit tests passing in 0.65s
  - [x] Total pipeline: ~15s (download-only) or ~3-5 min (with live scrape)

## Phase 2 — Enhancements

- [ ] **2A:** "New Today" diffing (⭐ new, ❌ gone)
- [ ] **2B:** Excel reports (openpyxl, colored rows, multiple sheets)
- [ ] **2C:** Application status tracker (JSON CRM)
- [ ] **2D:** LinkedIn job search (G-Stack, cookie auth validated)
- [ ] **2E:** LinkedIn connection mapper (🤝 badges)
- [ ] **2F:** Skill gap analysis (✅/❌ per job)
- [ ] **2G:** Resume engine (LaTeX + Weasyprint)
- [ ] **2H:** Interactive scoring calibration
- [ ] **Fix:** Netflix is on Workday, not Lever — update preferred_companies config
- [ ] **Improve:** company metadata coverage (9.8% → enable 3-tier scoring)

## Phase 3 — Nice-to-Have

- [ ] **3A:** CF Crawl for career URL discovery
- [ ] **3B:** Generic career page scraping (G-Stack)
- [ ] **3C:** Referral message drafter
- [ ] **3D:** Salary intelligence (Levels.fyi)
- [ ] **3E:** Job market trend analytics
- [ ] **3F:** Seed data auto-update script
- [ ] **3G:** Cover letter generator
- [ ] **3H:** Workable company discovery

## Killed Items

- ~~company_db.py~~ — Score at job level, not company level
- ~~intake.py~~ — YAML config is simpler
- ~~Full self-scrape as primary~~ — Download JBA's 502K instead
- ~~3-tier company scoring~~ — Only 9.8% metadata coverage
- ~~Pre-filtering before scoring~~ — 8s for 502K is fine

## Key Metrics

- [x] P1 accuracy: Top P1s are Netflix/Anthropic analytics/data roles ✅ Excellent
- [ ] False negatives: Need manual review of P3/P4 for missed good jobs
- [x] Runtime: 15s download-only, ~3-5 min with live scrape ✅ Under target
- [x] Coverage: Anthropic=450, 1Password=69 via live scrape ✅
- [x] Tests: 79/79 unit tests, 0.65s ✅
