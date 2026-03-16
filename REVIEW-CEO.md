# CEO Review — JobHunter AI (March 15, 2026)

## What We Have

A **working CLI job discovery tool** that downloads 502K jobs from 12K+ companies, scores them against a user profile, and produces a prioritized CSV report. Orchestrated via Claude skill ("find me jobs" → results in ~15s).

**Phase 1 is DONE:** 79/79 tests pass, full pipeline validated, top P1 matches are genuinely excellent (Netflix Analytics Engineer 97.9, Anthropic Analytics Data Engineer 92.8).

## The Honest Assessment

### ✅ What Works Well
1. **Data moat is real** — 502K jobs from 12K companies, refreshed daily for free (JBA GitHub data)
2. **Scoring quality is high** — P1 results are exactly the jobs Aditya should apply to
3. **Speed is great** — Full pipeline in ~15 seconds (download-only) or ~3-5 min (with live scrape)
4. **Coverage is massive** — 877 unique companies in P1+P2, including Netflix(49), Stripe(20), Anthropic(12), OpenAI(13), SpaceX(14)
5. **Engineering is solid** — Clean code, good tests, fault-tolerant, dual dedup

### 🚨 What's Broken (as a Product)

**1. ZERO DISTRIBUTION — Nobody can use this but Aditya + Claude**

The tool is a Python CLI orchestrated through a Claude skill file. To use it, you need:
- Python 3.13 venv set up
- Claude Code access with SKILL.md
- Technical ability to read a CSV and edit YAML

**This is not a product. It's a personal automation script.** Useful to one person. The philosophy of "building apps useful to most people" requires distribution.

**2. The output is UNUSABLE for humans**

- The CSV report is **95.6 MB / 477,807 rows** — includes ALL scored jobs including 465K P4 (garbage tier)
- No human opens a 95MB CSV. Excel will choke. Google Sheets won't even import it.
- The terminal summary is good but ephemeral — gone when Claude session ends
- No "what's new today?" — the #1 thing a job seeker wants

**3. No way to act on results**

- Find 61 P1 jobs → then what? No application tracking, no one-click apply, no saved state
- No way to mark "applied", "skip", "interested" — you just get a new list every day
- No way to see if a job from yesterday is still there or gone

**4. Single-user hardcoded**

- `config/profile.yaml` has Aditya's exact profile
- No onboarding for a new user — they'd need to hand-edit YAML
- No way to support multiple profiles

## What This Should Become

### Option A: Web Dashboard (Recommended)
**Effort: 2-3 days | Impact: Transformative**

A simple web UI (Flask + HTML/Tailwind) that:
- Shows today's P1/P2 matches as cards with score, title, company, location, apply link
- Has a "New Today ⭐" badge for jobs that weren't there yesterday
- Lets you filter by location, company, role type
- Lets you mark jobs as Applied/Skipped/Saved
- Has a simple profile setup page (replace YAML editing)
- Can be shared via a URL (deploy to Render/Railway for free)

**Why:** A URL is the universal distribution mechanism. "Check out jobhunter.app" vs "clone this repo, set up Python 3.13, edit YAML..."

### Option B: Daily Email/Slack Digest
**Effort: 1 day | Impact: High for power users**

- Cron job runs pipeline daily at 8am
- Sends HTML email with P1 matches + "new today" + quick stats
- Zero daily effort from user — jobs come to you

### Option C: Static HTML Report (Cheapest)
**Effort: 4 hours | Impact: Moderate**

- Generate a clean HTML file instead of/alongside CSV
- Self-contained, opens in any browser, searchable
- Can be hosted on GitHub Pages for free

## What to Kill from the Roadmap

| Planned Item | Verdict | Reason |
|---|---|---|
| Excel reports (2B) | **KILL** | Web UI replaces this entirely |
| LinkedIn scraping (2D, 2E) | **DEFER** | Legal risk, cookie maintenance burden, focus on core first |
| Resume engine (2G) | **DEFER** | Scope creep — this is a separate product |
| Cover letter generator (3G) | **KILL** | Claude already does this on demand |
| Salary intelligence (3D) | **DEFER** | Nice-to-have, not core |
| CF Crawl (3A) | **KILL** | 502K jobs is already massive coverage |

## What to BUILD NOW (Priority Order)

| # | Item | Effort | Why |
|---|---|---|---|
| 1 | **Fix the output** — CSV should be P1+P2+P3 only (12K rows, not 477K) | 30 min | Unusable as-is |
| 2 | **"New Today" diffing** — compare vs yesterday | 2 hr | #1 feature for job seekers |
| 3 | **Web dashboard** — Flask + simple HTML | 1 day | Distribution = product |
| 4 | **Application tracker** — mark applied/skipped | 4 hr | Turn discovery into workflow |
| 5 | **Profile onboarding page** — web form → profile.yaml | 2 hr | Let others use it |
| 6 | **Daily cron + email digest** — automated push | 4 hr | Zero-effort daily value |

## Key Metric to Watch

**Today: 1 user, 0 distribution channels.**
**Goal: Shareable URL + daily email within 1 week.**

The data engine is built. The scoring works. Now ship the interface.

---

*"A product nobody can reach is not a product."*
