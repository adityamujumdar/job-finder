# Engineering Review — JobHunter AI (March 15, 2026)

## Summary

Phase 1 MVP is functionally complete. 79/79 tests pass in 0.66s. Pipeline runs. Scoring quality is good. But there are **6 bugs, 4 cost/waste issues, and 3 architectural problems** that need fixing before building on top of this.

---

## 🔴 BUGS (Fix Immediately)

### BUG-1: Data Inconsistency Between Pipeline Steps
**Severity: HIGH**

`data/jobs/` has 2,297 jobs (live-only), but `data/scored/` has 477,776 jobs (full JBA run). These are from DIFFERENT pipeline runs. The scored file was produced from a full JBA download, then the scraper was re-run with `--skip-download` which overwrote `data/jobs/` with just 2,297 live-scraped jobs. The matcher was NOT re-run, so `data/scored/` is stale.

**Root cause:** No pipeline atomicity. Steps can be run independently and overwrite each other.

**Fix:** 
- Add a run manifest (`data/runs/YYYY-MM-DD-HHmmss.json`) that tracks which steps were run and with what params
- The matcher should validate that its input `data/jobs/` timestamp matches expectations
- OR: run all 3 steps atomically by default, make individual step runs opt-in with warnings

### BUG-2: Netflix Listed Under Lever, Actually on Workday
**Severity: MEDIUM**

`config/profile.yaml` line 69: `netflix` is listed under `lever:` preferred companies. Netflix is on Workday. The live scrape of Netflix via Lever silently returns 0 jobs (Lever API returns empty, no error). Netflix Workday jobs (906 of them) come through the JBA bulk download, so they still appear in results — but the "preferred company" live-scrape freshness benefit is lost.

**Fix:** Move Netflix to workday section with proper slug: `netflix|wd1|netflix`

### BUG-3: CSV Report is 95.6 MB / 477,807 Rows
**Severity: HIGH (usability)**

The report writes ALL scored jobs including 465,388 P4 jobs (score <50). No human will ever look at these. Excel can't even open a 95MB CSV reliably.

**Fix:** Default `report.py` to only include P1+P2+P3 (12,388 rows, ~2.5 MB). Add `--all` flag for full output.

### BUG-4: Scored JSON is 162 MB — Stores Full Job Objects
**Severity: MEDIUM (disk)**

`data/scored/YYYY-MM-DD.json` stores the ENTIRE job object for all 477K jobs plus score/priority fields. This is 162MB per day.

**Fix:** Only write P1+P2+P3 to scored output (12K jobs, ~5MB). Or store scores separately from job data.

### BUG-5: `launch2` is Top P1+P2 Company (374 jobs) — Likely a Recruiter
**Severity: LOW**

`launch2` has 374 P1+P2 matches — more than Netflix (49), Stripe (20), or Anthropic (12) combined. This is almost certainly a staffing/recruiting company that slipped through the `is_recruiter_company()` filter because "launch2" doesn't match any RECRUITER_TERMS.

**Fix:** Investigate `launch2`. If staffing, add to recruiter terms or create a manual blocklist.

### BUG-6: `relataboratories` Typo in Profile
**Severity: LOW**

PLAN.md line 282 has `relataboratories` as a preferred Greenhouse company. Profile.yaml line 67 has `relativityspace`. These don't match. Need to verify which slug is correct on Greenhouse.

---

## 🟡 COST & WASTE ISSUES

### WASTE-1: 413 MB of Data Per Day, No Cleanup
**Current state:**
```
data/jba/2026-03-15.json      154.0 MB  (raw JBA download cache)
data/scored/2026-03-15.json    162.2 MB  (all 477K scored jobs)
data/reports/2026-03-15.csv     95.6 MB  (all 477K rows)
data/jobs/2026-03-15.json        0.8 MB  (merged jobs)
                               ─────────
                               412.6 MB/day
```

After 7 days: **2.9 GB**. After 30 days: **12.4 GB**.

**Fix:**
1. Only keep last 3 days of JBA cache (delete older). Save ~450 MB.
2. Only write P1-P3 to scored/reports (save ~250 MB/day immediately).
3. Add `scripts/cleanup.sh` — rotate data older than 7 days.

### WASTE-2: Scoring All 477K Jobs When Only 12K Matter
**Current decision:** "Score all 502K jobs (~8s + 250MB acceptable; no false negatives from pre-filtering"

This was a reasonable V1 decision, but it causes the 162MB scored file and 95MB CSV. A lightweight pre-filter (title contains any target_role keyword OR any boost_keyword) would reduce to ~50K candidates with near-zero false negatives, then full scoring on those 50K.

**Impact:** Scored file goes from 162MB → ~15MB. CSV from 95MB → ~3MB. Scoring from 8s → <1s.

**Risk:** Minimal — anyone with "analytics", "data", "intelligence", "BI", "business", "engineer", "reporting", "dashboard" etc. in the title is kept. Pure SWE/Design/Sales/Legal titles (90%+ of jobs) are correctly skipped.

### WASTE-3: No HTTP Connection Pooling for Live Scrape
Live scrape loops sequentially over platforms/slugs in `scraper.py:scrape_preferred()`. Each `fetch_company_jobs()` call creates new HTTP connections. For 14 companies this is fine (~2s overhead), but for 100+ companies it adds up.

**Fix (when scaling):** Use `requests.Session()` per platform in the fetcher, or batch companies by platform using `fetch_all_jobs()` which already has ThreadPoolExecutor.

### WASTE-4: JBA Download Caches Uncompressed (154 MB vs 17 MB)
JBA data downloads as gzipped (~17MB) but is cached as uncompressed JSON (154MB). 9x bloat.

**Fix:** Cache as gzip: `json.dumps(data).encode()` → `gzip.compress()` → write. Load with `gzip.decompress()`. Saves 137MB/day.

---

## 🟠 ARCHITECTURAL ISSUES

### ARCH-1: No Pipeline State Management
Each step (scraper → matcher → report) reads/writes files independently. Nothing prevents:
- Running matcher on yesterday's jobs file when today's scraper already ran
- Running report on stale scored data
- Overwriting jobs with a partial run (--skip-download) then scoring against the old full scored file

**Fix:** Add a lightweight run manifest:
```json
// data/runs/2026-03-15.json
{
  "scraper": {"ran_at": "...", "params": {...}, "jobs_count": 502747},
  "matcher": {"ran_at": "...", "input_jobs": 502747, "scored": 477776},
  "report": {"ran_at": "...", "input_scored": 477776}
}
```
Matcher refuses to run if scraper hasn't run today. Report refuses if matcher is stale.

### ARCH-2: No README.md
There's no README. A new developer (or future-you) has to read PLAN.md (679 lines), CLAUDE.md, SKILL.md, and TODOS.md to understand the project. Need a concise README with: what it does, how to set up, how to run, what the output looks like.

### ARCH-3: Profile Assumes One User
`config/profile.yaml` is the single profile. If this becomes multi-user (web app), the profile loading needs to accept arbitrary profiles, not just a hardcoded path. The `load_profile()` function already accepts a `path` param, so this is mostly a design concern for the web layer.

---

## ✅ THINGS DONE RIGHT

| Area | Assessment |
|---|---|
| **Test coverage** | 79 unit tests, 0.66s, all passing. Good edge cases. |
| **Fault tolerance** | Chunk-level download recovery, cache fallback, missing field defaults |
| **Dedup strategy** | Dual-key (URL + composite) is battle-tested |
| **Scoring quality** | P1 results are excellent — Netflix, Anthropic, Stripe analytics roles |
| **Config/constants** | Centralized in `src/config.py`, not scattered |
| **Vendor management** | SHA-pinned with update script |
| **Code organization** | Clean separation: downloader → scraper → matcher → report |

---

## FIX PRIORITY (Effort/Impact Matrix)

| Priority | Issue | Effort | Impact |
|---|---|---|---|
| **P0** | BUG-3: CSV 95MB → P1-P3 only | 15 min | Massive — makes output usable |
| **P0** | BUG-4: Scored 162MB → P1-P3 only | 15 min | Massive — 97% disk savings |
| **P0** | WASTE-4: Cache JBA as gzip | 20 min | 137MB/day savings |
| **P1** | BUG-2: Fix Netflix to Workday | 5 min | Config fix, immediate |
| **P1** | BUG-1: Pipeline state manifest | 1 hr | Prevents data inconsistency |
| **P1** | WASTE-1: Data rotation script | 30 min | Prevents disk blowup |
| **P1** | ARCH-2: Write README.md | 30 min | Onboarding |
| **P2** | WASTE-2: Pre-filter before scoring | 1 hr | 10x faster scoring, 10x smaller output |
| **P2** | BUG-5: Investigate launch2 | 15 min | Scoring accuracy |
| **P2** | BUG-6: Verify relativityspace slug | 5 min | Config correctness |
| **P3** | ARCH-1: Full pipeline manifest | 2 hr | Robustness |
| **P3** | WASTE-3: Connection pooling | 30 min | Only matters at scale |

---

## Cost Summary

| Resource | Current | After Fixes |
|---|---|---|
| **Disk per day** | 413 MB | ~25 MB (gzip cache + P1-P3 only) |
| **Disk per month** | 12.4 GB | ~750 MB |
| **GitHub API calls** | ~22/day (free) | Same |
| **Live scrape HTTP** | ~14 requests/day | Same |
| **Cloud hosting** | $0 (local only) | $0-5/mo (free tier web host) |
| **Pipeline runtime** | ~15s (download) / ~3-5min (full) | Same |

**Total operating cost: $0.** The only cost is disk space, which the fixes above reduce by 94%.

---

## Recommended Fix Order (1 Session)

```
1. Fix CSV + Scored to P1-P3 only        (30 min)  → output usable
2. Fix Netflix config                     (5 min)   → data accuracy
3. Add gzip JBA cache                    (20 min)  → disk savings
4. Add data rotation (keep 7 days)        (30 min)  → disk management
5. Investigate launch2                    (15 min)  → scoring accuracy
6. Write README.md                        (30 min)  → onboarding
                                          ─────────
                                          ~2.5 hours
```

After these 6 fixes, the engine is solid and ready for the web layer.
