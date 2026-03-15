# TODOS — JobHunter AI

## Phase 1 Quick Wins (build during Phase 1)

### Delight 1: 🤝 "Connection at Company" Badge (~15 min)
Cross-reference matched jobs with LinkedIn connections. Show badge + contact name in report.
"Google — BI Manager (P1: 95%) 🤝 Jane Doe is a Senior Analyst there."
**Build with:** report.py, after network.py is done.

### Delight 2: Skill Gap Analysis per Job (~20 min)
For P1/P2 jobs, show: "✅ Python, SQL, Tableau | ❌ Missing: Spark, dbt | 💡 Your SQL transfers to dbt."
**Build with:** matcher.py already computes skill overlap — just format it.

### Delight 4: ⭐ "New Today" / ❌ "Filled" Badges (~15 min)
Diff today's jobs vs yesterday's. Mark new jobs with ⭐, disappeared jobs with ❌.
"5 new P1 jobs today! 2 from yesterday no longer listed."
**Build with:** report.py, compare data/jobs/today.json vs data/jobs/yesterday.json.

---

## Phase 2 Items

### TODO 1: Application Status CRM / Pipeline Tracker (P1, M)
**What:** Track status per job: Not Applied → Applied → Phone Screen → Interview → Offer → Rejected.
**Why:** Without tracking, users apply to the same job twice or lose track of pipeline.
**Pros:** Makes the tool a daily driver "job search OS" vs one-off "job finder."
**Cons:** Requires user to update statuses (Claude can prompt). ~2-3hr.
**Context:** Simple JSON-backed status tracker. Claude prompts: "You applied to Google BI Manager 5 days ago. Any updates?" Daily report shows pipeline summary.
**Effort:** M (2-3 hours)
**Priority:** P1
**Depends on:** report.py

### TODO 2: Salary Intelligence Module (P2, L)
**What:** Scrape salary data from Levels.fyi and Glassdoor for matched companies/roles.
**Why:** Users can't negotiate effectively without market data.
**Pros:** Transforms report from "here are jobs" to "here are jobs AND what they pay."
**Cons:** Anti-scraping measures on both sites. ~4-6hr to build + maintain.
**Context:** Start with Levels.fyi (more API-friendly). G-Stack + cookies for Glassdoor auth.
**Effort:** L (4-6 hours)
**Priority:** P2
**Depends on:** gstack_client.py, fetchers framework

### TODO 3: Referral Message Drafter (P2, M)
**What:** Auto-draft LinkedIn/email messages asking connections for referrals.
**Why:** Referrals are #1 hiring channel. Pre-drafted messages remove friction.
**Pros:** Turns network data into action. Claude excels at personalized messages.
**Cons:** Risk of feeling generic/spammy. ~2hr.
**Context:** Combines network mapper + job match data.
**Effort:** M (2 hours)
**Priority:** P2
**Depends on:** network.py, matcher.py

---

## Phase 3 Items

### TODO 4: Job Market Trend Analytics (P3, M)
**What:** Track postings over time. Weekly trend charts with matplotlib.
**Why:** Strategic intelligence for timing applications.
**Pros:** Data is a byproduct of daily scraping (free to accumulate).
**Cons:** Needs 2+ weeks of data. ~3hr.
**Effort:** M (3 hours)
**Priority:** P3
**Depends on:** 2+ weeks of daily data

### TODO 5: Seed Data Auto-Update (P2, S)
**What:** Script to re-download community company lists from GitHub repos monthly.
**Why:** New companies join Greenhouse/Lever constantly. Seed data goes stale.
**Context:** `python3 src/update_seeds.py` fetches latest from job-board-aggregator + awesome-easy-apply.
**Effort:** S (1 hour)
**Priority:** P2
**Depends on:** Initial seed data setup

### TODO 6: Cloudflare Crawl API Upgrade (P3, S)
**What:** If user upgrades to Cloudflare paid tier, expand CF Crawl role beyond URL discovery.
**Why:** Paid tier has higher rate limits, could replace G-Stack for non-auth pages.
**Context:** Current free tier: ~2-3 calls/min. Paid tier: significantly higher. Would need cf_client.py changes.
**Effort:** S (1 hour)
**Priority:** P3
**Depends on:** User upgrading Cloudflare account

---

## Eng Review Findings (Addressed in Plan)

- ~~BaseScraper class hierarchy~~ → Replaced with simple fetcher functions
- ~~Browser scraping for Greenhouse/Lever~~ → Replaced with public JSON APIs
- ~~Google-search company discovery~~ → Replaced with community seed data
- ~~Cloudflare as primary scraping engine~~ → Scoped to URL discovery only
- ~~Sequential API fetching~~ → ThreadPoolExecutor with 10 workers
- ~~8,956 companies daily~~ → Relevance-filtered 200-500
