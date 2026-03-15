# JobHunter AI — Consolidated Plan
## Post CEO Review (SCOPE EXPANSION) + Eng Review (BIG CHANGE)

---

## Executive Summary

A Claude skill (GitHub-publishable) that automates the entire job search lifecycle. The key architectural insight from eng review: **Greenhouse, Lever, Workday, Ashby, and BambooHR all have free public JSON APIs** — no browser scraping needed for ~90% of companies. G-Stack headless browser is reserved for LinkedIn (requires auth) and custom career pages. Cloudflare Crawl API supplements for career URL discovery only.

## Decision Log (CEO + Eng Reviews Combined)

| # | Decision | Choice | Source |
|---|----------|--------|--------|
| 0 | Mode | SCOPE EXPANSION → BIG CHANGE (restructured) | CEO→Eng |
| 1 | Cookie auth check | Pre-scrape auth check for LinkedIn | CEO |
| 2 | LaTeX validation | Validate + auto-fix + Weasyprint fallback | CEO |
| 3 | Orchestration | Claude calls Python CLIs via Bash | CEO |
| 4 | LinkedIn blocking | Multi-signal detection + halt | CEO |
| 5 | Secrets | .env pattern, no tokens in code | CEO |
| 6 | .gitignore | Create FIRST before any code | CEO |
| 7 | PDF job descriptions | Parse with pdfplumber | CEO |
| 8 | G-Stack wrapper | GStackBrowser Python class | CEO |
| 9 | Scraper pattern | **Simple fetcher functions** (not BaseScraper class) | Eng override |
| 10 | Test fixtures | JSON API fixtures + HTML for LinkedIn/generic only | Eng update |
| 11 | URL caching | Cache with 7-day TTL | CEO |
| 12 | Resume fallback | HTML+Weasyprint alongside LaTeX | CEO |
| 13 | Company data | **Embed community lists** (8,956 companies) | Eng new |
| 14 | CF Crawl role | **URL discovery only**, not bulk scraping | Eng new |
| 15 | Parallelization | ThreadPoolExecutor, 10 workers + jitter | Eng new |
| 16 | Daily scope | Relevance-filtered ~200-500 companies, full sweep weekly | Eng new |
| 17 | CF client | Dedicated `cf_client.py` | Eng new |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                        JOBHUNTER AI — CLAUDE SKILL                                │
│                                                                                   │
│  ORCHESTRATION (SKILL.md → Claude → Bash → Python CLIs)                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │ Claude reads SKILL.md, calls:                                               │  │
│  │   python3 src/intake.py                                                     │  │
│  │   python3 src/scraper.py --profile data/profile.json --daily                │  │
│  │   python3 src/matcher.py --jobs data/jobs/today.json --profile ...          │  │
│  │   python3 src/report.py --scored data/scored/today.json                     │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  ════════════════════════════════════════════════════════════════════════════════  │
│  TIER 1: PUBLIC JSON APIs  (fast, reliable, 90% of companies)                    │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │Greenhouse│ │  Lever   │ │ Workday  │ │  Ashby   │ │BambooHR  │               │
│  │  API     │ │  API     │ │  API     │ │  API     │ │  API     │               │
│  │          │ │          │ │          │ │          │ │          │               │
│  │ boards-  │ │ api.     │ │ company. │ │ jobs.    │ │ slug.    │               │
│  │ api.     │ │ lever.co │ │ wd5.my.. │ │ ashbyhq. │ │ bamboohr │               │
│  │ green..  │ │ /v0/     │ │ jobs.com │ │ com/api  │ │ .com/    │               │
│  │ .io/v1/  │ │ postings │ │          │ │ graphql  │ │ careers  │               │
│  │          │ │          │ │          │ │          │ │ /list    │               │
│  │ 4,516 co │ │ 947 co   │ │ 3,493 co │ │  ~200 co │ │ ~300 co  │               │
│  │ GET JSON │ │ GET JSON │ │POST JSON │ │POST GQL  │ │ GET JSON │               │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘               │
│       │            │            │            │            │                       │
│       └────────────┴────────────┴────────────┴────────────┘                       │
│                              │                                                    │
│                    ┌─────────▼──────────┐                                         │
│                    │  ThreadPoolExecutor │                                         │
│                    │  10 workers + jitter│                                         │
│                    │  ~200-500 co/day    │                                         │
│                    └─────────┬──────────┘                                         │
│                              │                                                    │
│  ════════════════════════════▼═══════════════════════════════════════════════════  │
│  TIER 2: G-STACK BROWSER  (auth-required, interactive — ~10% of scraping)        │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  ┌───────────────────────────┐  ┌────────────────────────────┐                   │
│  │  LinkedIn Scraper         │  │  Generic Career Page        │                   │
│  │                           │  │                             │                   │
│  │  cookie-import-browser    │  │  G-Stack browse + text      │                   │
│  │  goto → snapshot → text   │  │  For companies NOT on any   │                   │
│  │  Rate: 2s/page, max 10pg │  │  standard ATS platform      │                   │
│  │  Block detection:         │  │  HTML parsing fallback      │                   │
│  │    CAPTCHA, 999, empty,   │  │                             │                   │
│  │    "unusual activity"     │  │  PDF jobs → pdfplumber      │                   │
│  └───────────────────────────┘  └────────────────────────────┘                   │
│                                                                                   │
│  ════════════════════════════════════════════════════════════════════════════════  │
│  TIER 3: CLOUDFLARE CRAWL API  (supplementary — URL discovery only)              │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │  Account: 4ad7fecaa8e549154093d6f147f77195                                 │  │
│  │  Token: env var CLOUDFLARE_API_TOKEN                                        │  │
│  │                                                                             │  │
│  │  /content  (sync)  — single page JS-rendered HTML. Use for URL discovery.  │  │
│  │  /crawl    (async) — follows links, 10 pages default. Career page mapping. │  │
│  │  /scrape   (sync)  — CSS selector extraction. Structured data from pages.  │  │
│  │                                                                             │  │
│  │  CONSTRAINTS: Free tier ~2-3 calls/min. Rate limit 2001 = graceful degrade │  │
│  │  USE: Find career URLs for user-specified companies not on standard ATS.    │  │
│  │  NOT FOR: Bulk job scraping. Falls back to G-Stack when rate limited.       │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  ════════════════════════════════════════════════════════════════════════════════  │
│  PROCESSING PIPELINE                                                              │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ normalize│─▶│ dedup    │─▶│ match    │─▶│ rank     │─▶│ report   │           │
│  │ all jobs │  │ hash on  │  │ score vs │  │ P1-P4    │  │ .xlsx    │           │
│  │ to common│  │ company+ │  │ profile  │  │ tiers    │  │ .csv     │           │
│  │ schema   │  │ title+   │  │ weighted │  │          │  │ summary  │           │
│  │          │  │ location │  │ 8 factors│  │          │  │          │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│                                                                                   │
│  ════════════════════════════════════════════════════════════════════════════════  │
│  RESUME ENGINE                                                                    │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                │
│  │  Designer         │  │  Generator        │  │  Compiler         │                │
│  │  Colors, fonts,   │  │  LaTeX + HTML     │  │  pdflatex (pri)   │                │
│  │  margins, layout  │  │  templates        │  │  Weasyprint (fb)  │                │
│  │  ATS-safe rules   │  │  Tailor per job   │  │  Auto-fix errors  │                │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘                │
│                                                                                   │
│  ════════════════════════════════════════════════════════════════════════════════  │
│  DATA LAYER (all local, all gitignored)                                           │
│  ════════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  config/config.yaml       ← preferences, preferred companies, search params       │
│  data/seed/               ← community company lists (committed, updated monthly)  │
│  data/profile.json        ← parsed user profile (gitignored)                      │
│  data/companies.json      ← merged company DB w/ relevance scores (gitignored)    │
│  data/connections.json    ← LinkedIn connections (gitignored)                      │
│  data/jobs/YYYY-MM-DD.json     ← daily raw jobs                                  │
│  data/scored/YYYY-MM-DD.json   ← daily scored jobs                               │
│  data/reports/YYYY-MM-DD.xlsx  ← daily Excel report                              │
│  data/logs/*.log               ← run logs                                         │
│  resumes/                      ← base + tailored resumes (gitignored)             │
│  .env                          ← CLOUDFLARE_API_TOKEN etc (gitignored)            │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## Company Seed Data Strategy

```
SEED SOURCES (shipped with skill):
  ├── data/seed/greenhouse_companies.json    4,516 slugs
  ├── data/seed/lever_companies.json           947 slugs
  ├── data/seed/workday_companies.json       3,493 slugs
  ├── data/seed/ashby_companies.json          ~200 slugs
  └── data/seed/bamboohr_companies.json       ~300 slugs
                                             ──────
                                             9,456 total

ENRICHMENT:
  ├── awesome-easy-apply (800+ with descriptions, locations, LinkedIn URLs)
  ├── Google dorking: site:boards.greenhouse.io, site:jobs.lever.co
  ├── GitHub community lists (updated periodically)
  └── User-provided companies in config.yaml

DAILY FILTER (relevance_score):
  ├── User preferred companies         → always fetch (score: 100)
  ├── Industry match + location match  → fetch daily   (score: 70+)
  ├── Industry match only              → fetch 2x/week (score: 40-69)
  └── No match                         → fetch weekly   (score: <40)
  Target: ~200-500 companies per daily run
```

---

## Cloudflare Crawl API — Integration Spec

```
ENDPOINT REFERENCE:
  POST /accounts/{id}/browser-rendering/content
    Input:  {"url": "https://example.com"}
    Output: {"success": true, "result": "<html>...", "meta": {"status": 200, "title": "..."}}
    Type:   Synchronous, single page, JS-rendered

  POST /accounts/{id}/browser-rendering/crawl
    Input:  {"url": "https://example.com"}
    Output: {"success": true, "result": "task-uuid"}
    Poll:   GET /accounts/{id}/browser-rendering/crawl/{task-id}
    Result: {records: [{url, status, metadata, html}, ...]}
    Type:   Async, follows links, default 10 pages

  POST /accounts/{id}/browser-rendering/scrape
    Input:  {"url": "...", "elements": [{"selector": "a"}]}
    Output: Structured extraction by CSS selector
    Type:   Synchronous

RATE LIMITS (free tier, tested):
  ~2-3 calls/minute across ALL endpoints
  Error code 2001 = rate limit exceeded
  Recovery: wait 60s+ (aggressive)

WHAT WORKS:
  ✅ example.com → full HTML in 0.34s
  ✅ Figma careers → 10 pages, 166 Greenhouse job links, 13 browser-sec
  ✅ /content for single-page JS-rendered content

WHAT DOESN'T:
  ❌ Cloudflare-protected sites (403 — even Lever which is Cloudflare's own!)
  ❌ Bulk scraping (rate limits make >3 calls/min impossible)
  ❌ Sites requiring auth (no cookie support)

INTEGRATION PATTERN:
  cf_client.py:
    class CloudflareCrawlClient:
        def __init__(self, account_id, api_token):
            self.base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering"
            self.headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

        def fetch_content(self, url) -> dict:
            """Sync single-page fetch. Returns {"html": "...", "title": "...", "status": 200}"""
            resp = requests.post(f"{self.base}/content", headers=self.headers, json={"url": url})
            if resp.status_code == 429 or (resp.json().get("errors") and resp.json()["errors"][0]["code"] == 2001):
                raise RateLimitError("Cloudflare rate limit hit")
            return resp.json()

        def crawl(self, url) -> str:
            """Async crawl. Returns task_id. Poll with poll_crawl()."""
            ...

        def poll_crawl(self, task_id, timeout=60) -> dict:
            """Poll until crawl completes or times out."""
            ...

  USAGE IN PIPELINE:
    1. User adds "CompanyX" to preferred companies in config.yaml
    2. CompanyX not in Greenhouse/Lever/Workday seed data
    3. cf_client.fetch_content("https://companyx.com/careers") → HTML
    4. Parse HTML for ATS links (Greenhouse? Lever? Custom?)
    5. If Greenhouse/Lever found → add slug to company DB, use API next time
    6. If custom page → store URL, use G-Stack generic scraper
    7. If CF rate limited → fallback to G-Stack Google search
```

---

## G-Stack + Cookie Integration Spec

```
DECISION MATRIX — WHEN TO USE WHAT:

  TASK                              │ TOOL           │ WHY
  ──────────────────────────────────┼────────────────┼─────────────────────────────
  Greenhouse/Lever/Workday jobs     │ Public JSON API│ Structured data, no browser
  Ashby/BambooHR jobs               │ Public JSON API│ Same — APIs exist
  LinkedIn job search               │ G-Stack+cookies│ MUST have auth, interactive
  LinkedIn connection mapping       │ G-Stack+cookies│ MUST have auth, infinite scroll
  Custom career page scraping       │ G-Stack browse │ No API, need JS rendering
  Career URL discovery (new co.)    │ CF Crawl first │ Fast, no local browser needed
  Career URL discovery (fallback)   │ G-Stack Google │ When CF rate limited
  PDF job description extraction    │ G-Stack+Python │ Download via browse, parse w/ pdfplumber
  Authentication state check        │ G-Stack browse │ goto linkedin.com/feed, check redirect

G-STACK COOKIE WORKFLOW:
  1. First run: $B cookie-import-browser chrome --domain .linkedin.com
  2. Each daily run: $B goto https://linkedin.com/feed → check URL
     - If URL contains "login" or "authwall" → cookies expired
     - Prompt: "LinkedIn session expired. Run: $B cookie-import-browser chrome --domain .linkedin.com"
  3. After re-import: verify again before proceeding
  4. Cookie state persists across G-Stack sessions (stored in .gstack/)

G-STACK LINKEDIN SCRAPING PATTERN:
  $B cookie-import-browser chrome --domain .linkedin.com
  $B goto "https://www.linkedin.com/jobs/search/?keywords=business+intelligence&location=Arizona"
  $B wait --networkidle
  $B snapshot -i                    # see job cards with @refs
  $B text                           # extract all text (job titles, companies, locations)
  # Pagination: scroll, click "See more jobs", repeat
  # Rate: 2s delay between actions, max 10 pages
  # Block detection after each page: check for CAPTCHA, 999, "unusual activity"
```

---

## Match Scoring Algorithm

```
MATCH_SCORE(job, profile) → float [0, 100]

WEIGHTS:
  skill_match:        0.30  ← |intersection(job.skills, profile.skills)| / |job.skills|
  experience_match:   0.15  ← gaussian(profile.years - job.min_years, σ=2)
  location_match:     0.15  ← exact_city=1.0, same_state=0.8, remote_ok=1.0, relocate=0.5
  industry_match:     0.10  ← direct=1.0, adjacent=0.7, transferable=0.4
  company_preference: 0.10  ← preferred=1.0, neutral=0.5, avoid=0.0
  network_score:      0.10  ← min(connections_at_company / 3, 1.0)
  recency:            0.05  ← max(0, 1 - days_since_posted / 30)
  work_arrangement:   0.05  ← exact_match=1.0, partial=0.5, mismatch=0.0

SKILL EXTRACTION FROM JOB DESCRIPTIONS:
  Job descriptions from Greenhouse API include full HTML content.
  Claude (or regex) extracts required skills from description text.
  Fuzzy matching: "SQL Server" matches "SQL", "Tableau" matches "Tableau Desktop"

PRIORITY TIERS:
  P1 (90-100): Apply immediately
  P2 (75-89):  Apply this week
  P3 (60-74):  Apply if time
  P4 (<60):    Save for later
```

---

## Resume Design System

```
┌─────────────────────────────────────────────────────────────────┐
│  RESUME DESIGN DECISIONS                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  MARGINS:    Narrow-Medium (0.5in sides, 0.4in top/bottom)       │
│  FONTS:      Sans-serif (Helvetica Neue / Source Sans Pro)        │
│              Name: 22pt bold | Headers: 12pt SC | Body: 10pt     │
│  COLORS:     Navy (#1a365d), Teal (#0d9488), Slate (#475569),   │
│              Rust (#9a3412), or Custom hex codes                  │
│  LAYOUT:     Single column, ATS-safe                              │
│              Header → Summary → Experience → Skills →             │
│              Education → Projects → Certifications                │
│  LINKS:      \faLinkedin \faGithub \faGlobe \faEnvelope \faPhone │
│              All clickable, colored accent                        │
│  BULLETS:    Action verb + quantified achievement, max 4-5/role  │
│  ATS-SAFE:   No tables in body, standard headings, no images     │
│  PAGE LIMIT: 1 page (<10yr) / 2 pages (10yr+), auto-sizing      │
│  DUAL ENGINE: LaTeX (primary) + HTML/Weasyprint (fallback)       │
│  TAILORING:  Reorder skills, adjust summary, highlight relevant  │
│              experience per job description                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure (Final, Post Eng Review)

```
jobhunter-ai/
├── SKILL.md                          # Claude skill entry point
├── README.md                         # GitHub README: setup, usage, examples
├── PLAN.md                           # This document
├── TODOS.md                          # Deferred work items
├── LICENSE                           # MIT
├── .gitignore                        # CRITICAL: first file created
├── .env.example                      # CLOUDFLARE_API_TOKEN=xxx
├── requirements.txt                  # Python deps (pinned)
├── setup.sh                          # One-time setup
│
├── config/
│   ├── config.yaml.example           # User prefs, preferred companies
│   └── companies.yaml.example        # Extra companies to always search
│
├── data/
│   ├── seed/                         # COMMITTED — community company lists
│   │   ├── greenhouse_companies.json # 4,516 slugs
│   │   ├── lever_companies.json      # 947 slugs
│   │   ├── workday_companies.json    # 3,493 slugs
│   │   ├── ashby_companies.json      # ~200 slugs
│   │   └── bamboohr_companies.json   # ~300 slugs
│   │
│   ├── profile.json                  # GITIGNORED — user profile
│   ├── companies.json                # GITIGNORED — merged company DB
│   ├── connections.json              # GITIGNORED — LinkedIn connections
│   ├── jobs/                         # GITIGNORED — daily raw jobs
│   ├── scored/                       # GITIGNORED — daily scored jobs
│   ├── reports/                      # GITIGNORED — Excel/CSV reports
│   ├── logs/                         # GITIGNORED — run logs
│   └── debug/                        # GITIGNORED — failed parse HTML (3-day retention)
│
├── src/
│   ├── __init__.py
│   ├── intake.py                     # CLI: profile questionnaire + resume parser
│   ├── company_db.py                 # CLI: merge seed + config → companies.json
│   ├── scraper.py                    # CLI: orchestrator — routes to fetchers
│   ├── matcher.py                    # CLI: scoring + ranking
│   ├── network.py                    # CLI: LinkedIn connection mapper (G-Stack)
│   ├── report.py                     # CLI: Excel/CSV generation
│   ├── cover_letter.py               # CLI: cover letter generator
│   │
│   ├── gstack_client.py              # GStackBrowser wrapper class
│   ├── cf_client.py                  # CloudflareCrawlClient wrapper class
│   ├── text_sanitizer.py             # LaTeX + HTML sanitization
│   ├── io_utils.py                   # JSON/YAML read/write, logging setup
│   ├── normalize.py                  # Shared job normalization schema
│   │
│   ├── fetchers/                     # Simple functions, NOT class hierarchy
│   │   ├── __init__.py
│   │   ├── greenhouse.py             # fetch_greenhouse_jobs(slug) → [Job]
│   │   ├── lever.py                  # fetch_lever_jobs(slug) → [Job]
│   │   ├── workday.py                # fetch_workday_jobs(slug) → [Job]
│   │   ├── ashby.py                  # fetch_ashby_jobs(slug) → [Job]
│   │   ├── bamboohr.py               # fetch_bamboohr_jobs(slug) → [Job]
│   │   ├── linkedin.py               # scrape_linkedin_jobs(browser, queries) → [Job]
│   │   └── generic.py                # scrape_generic_page(browser, url) → [Job]
│   │
│   └── resume/
│       ├── __init__.py
│       ├── generator.py              # LaTeX + HTML resume generator
│       ├── designer.py               # Design decisions engine
│       ├── tailor.py                  # Per-job tailoring
│       ├── compiler.py               # pdflatex + weasyprint + auto-fix
│       └── templates/
│           ├── modern.tex
│           ├── classic.tex
│           ├── minimal.tex
│           ├── modern.html
│           └── modern.css
│
├── resumes/                          # GITIGNORED
│   ├── base_resume.tex
│   └── tailored/
│
└── tests/
    ├── __init__.py
    ├── fixtures/
    │   ├── greenhouse_anthropic.json # Real API response, saved once
    │   ├── lever_example.json
    │   ├── workday_example.json
    │   ├── linkedin_search.html      # Saved LinkedIn search page
    │   └── generic_careers.html
    ├── test_fetchers.py              # All API fetcher tests
    ├── test_linkedin.py              # LinkedIn G-Stack scraper tests
    ├── test_matcher.py
    ├── test_report.py
    ├── test_resume.py
    ├── test_gstack_client.py
    ├── test_cf_client.py
    └── mock_gstack.py                # MockGStackBrowser for testing
```

---

## Daily Workflow

```
DAILY RUN (Claude skill or cron):

  1. PRE-FLIGHT
     ├── Verify G-Stack binary
     ├── Verify Python venv + deps
     ├── Load config.yaml
     ├── Check LinkedIn cookies (G-Stack → goto linkedin.com/feed → check redirect)
     └── If stale → prompt cookie re-import → halt if unresolved

  2. BUILD COMPANY LIST
     ├── Load seed data (greenhouse/lever/workday/ashby/bamboohr slugs)
     ├── Load user preferred companies from config.yaml
     ├── Load companies.json (with relevance scores)
     ├── Filter: daily run = score 70+ AND all user-preferred
     └── Output: ~200-500 target companies with ATS type + slug

  3. FETCH JOBS — TIER 1 (parallel, ~2-3 min)
     ├── ThreadPoolExecutor(max_workers=10)
     ├── For each company: call appropriate fetcher by ATS type
     │   ├── Greenhouse: requests.get(boards-api.greenhouse.io/v1/boards/{slug}/jobs)
     │   ├── Lever: requests.get(api.lever.co/v0/postings/{slug})
     │   ├── Workday: requests.post(company.wd5.myworkdayjobs.com/...)
     │   ├── Ashby: requests.post(jobs.ashbyhq.com/api/non-user-graphql)
     │   └── BambooHR: requests.get({slug}.bamboohr.com/careers/list)
     ├── 50ms random jitter between requests per worker
     └── On error: log, skip company, continue

  4. FETCH JOBS — TIER 2 (sequential, ~5-10 min)
     ├── LinkedIn: G-Stack with cookies
     │   ├── Search queries generated from profile
     │   ├── 2s delay between pages, max 10 pages
     │   ├── Block detection after each page
     │   └── On block: HALT, save progress, report
     └── Custom career pages: G-Stack generic parser
         ├── Companies not on any standard ATS
         └── PDF job descriptions → pdfplumber

  5. PROCESS
     ├── Normalize all jobs to common schema (normalize.py)
     ├── Deduplicate: hash(company + title + location)
     ├── Score each job vs profile (matcher.py)
     ├── Rank by match score → assign P1-P4
     └── Cross-reference with connections.json (🤝 badges)

  6. OUTPUT
     ├── data/jobs/YYYY-MM-DD.json (raw)
     ├── data/scored/YYYY-MM-DD.json (scored)
     ├── data/reports/YYYY-MM-DD.xlsx
     │   ├── Sheet 1: Priority Jobs (P1-P4)
     │   ├── Sheet 2: All Jobs
     │   ├── Sheet 3: Companies Status
     │   └── Sheet 4: Run Summary
     ├── data/reports/YYYY-MM-DD.csv
     └── data/logs/scrape_YYYY-MM-DD.log

  7. SUMMARY
     └── Claude: "Found X new jobs (Y new today). Z are P1. Top: [Co] [Role] (95%)"
```

---

## Build Order

```
PHASE 1A — Infrastructure (Day 1):
  1. .gitignore                                ← FIRST
  2. .env.example
  3. setup.sh + requirements.txt
  4. src/io_utils.py
  5. src/normalize.py (Job dataclass/schema)
  6. src/gstack_client.py (GStackBrowser)
  7. src/cf_client.py (CloudflareCrawlClient)
  8. src/text_sanitizer.py
  9. tests/mock_gstack.py

PHASE 1B — Data Layer (Day 1):
  10. Download + commit seed data to data/seed/
  11. config/config.yaml.example
  12. src/company_db.py + tests

PHASE 1C — API Fetchers (Day 1-2):
  13. src/fetchers/greenhouse.py + tests + fixture
  14. src/fetchers/lever.py + tests + fixture
  15. src/fetchers/workday.py + tests + fixture
  16. src/fetchers/ashby.py + tests
  17. src/fetchers/bamboohr.py + tests

PHASE 1D — G-Stack Fetchers (Day 2):
  18. src/fetchers/linkedin.py + tests + fixture
  19. src/fetchers/generic.py + tests + fixture

PHASE 1E — Core Pipeline (Day 2-3):
  20. src/intake.py + tests
  21. src/scraper.py (orchestrator) + tests
  22. src/matcher.py + tests
  23. src/report.py + tests

PHASE 1F — Resume Engine (Day 3-4):
  24. src/resume/designer.py
  25. src/resume/templates/*.tex + *.html + *.css
  26. src/resume/generator.py + tests
  27. src/resume/compiler.py + tests
  28. src/resume/tailor.py + tests

PHASE 1G — Extensions (Day 4-5):
  29. src/network.py + tests (LinkedIn connections)
  30. src/cover_letter.py + tests

PHASE 1H — Packaging (Day 5):
  31. SKILL.md
  32. README.md (with screenshots)
  33. Integration test (full daily run)
  34. GitHub publish
```

---

## Error & Rescue Registry

```
METHOD/CODEPATH                    | ERROR              | RESCUED | ACTION                      | USER SEES
-----------------------------------|--------------------|---------|-----------------------------|--------------------------
fetchers/greenhouse.py             | HTTP 404           | Y       | Skip, log                   | "[co] not found, skipped"
fetchers/greenhouse.py             | Network timeout    | Y       | Retry 2x, skip              | "[co] timeout, skipped"
fetchers/lever.py                  | Empty response     | Y       | Expected, skip              | Nothing (normal)
fetchers/workday.py                | Changed URL pattern| Y       | Log + generic fallback      | "[co] Workday URL changed"
fetchers/linkedin.py               | Cookie expired     | Y       | Pre-scrape auth check       | "Re-import cookies"
fetchers/linkedin.py               | CAPTCHA/999/block  | Y       | HALT, save progress         | "LinkedIn blocked. Wait 24h"
fetchers/linkedin.py               | Rate limit         | Y       | Exponential backoff         | "Rate limited. Waiting..."
fetchers/generic.py                | Unknown HTML struct | Y       | Best-effort parse + log     | "Partial results for [co]"
cf_client.py                       | Rate limit 2001    | Y       | Fallback to G-Stack         | "CF rate limited, using browser"
cf_client.py                       | 403 on target      | Y       | Fallback to G-Stack         | "CF blocked, using browser"
scraper.py (orchestrator)          | ThreadPool error   | Y       | Fallback to sequential      | "Parallel fetch failed, going sequential"
matcher.py                         | Missing job fields | Y       | Score 0, skip in ranking    | Job appears with "?" fields
report.py                          | openpyxl missing   | Y       | pip install hint            | Install instructions
report.py                          | 0 jobs found       | Y       | Empty report + message      | "No new jobs today"
resume/compiler.py                 | pdflatex missing   | Y       | Weasyprint fallback         | "Using HTML→PDF (install MacTeX for LaTeX)"
resume/compiler.py                 | LaTeX syntax error  | Y       | Auto-fix attempt, retry     | "Fixed LaTeX error on line X"
gstack_client.py                   | Binary not found   | Y       | Setup instructions          | "G-Stack not installed"
gstack_client.py                   | Chromium crash     | Y       | Auto-restart, retry once    | "Browser restarted"
```

---

## Failure Modes Registry

```
CODEPATH              | FAILURE MODE           | RESCUED | TEST | USER SEES        | LOGGED | STATUS
----------------------|------------------------|---------|------|------------------|--------|--------
Greenhouse API fetch  | Company removed board  | Y       | Y    | "Skipped"        | Y      | OK
Lever API fetch       | 0 jobs returned        | Y       | Y    | Silent (normal)  | Y      | OK
Workday API fetch     | URL pattern changed    | Y       | Y    | "URL changed"    | Y      | OK
LinkedIn scrape       | Cookie expired         | Y       | Y    | "Re-import"      | Y      | OK
LinkedIn scrape       | IP blocked             | Y       | Y    | "Wait 24h"       | Y      | OK
LinkedIn scrape       | Mid-scrape failure     | Y       | Y    | Progress saved   | Y      | OK
CF Crawl              | Rate limit             | Y       | Y    | Fallback to GS   | Y      | OK
CF Crawl              | Target 403             | Y       | Y    | Fallback to GS   | Y      | OK
Generic page scrape   | Unparseable HTML       | Y       | Y    | "Partial results"| Y      | OK
Job dedup             | Different URLs same job| Partial | Y    | Possible dupes   | Y      | WARN
Match scoring         | No skills in job desc  | Y       | Y    | Score based on   | Y      | OK
                      |                        |         |      | other factors    |        |
LaTeX compile         | Missing package        | Y       | Y    | Auto-install     | Y      | OK
Report generation     | Disk full              | Y       | Y    | "Disk full"      | Y      | OK
ThreadPool            | Worker crash           | Y       | Y    | Sequential fallbk| Y      | OK
```

**0 CRITICAL GAPS.** All failure modes rescued, tested, visible, logged.

---

## NOT in Scope

| Item | Rationale |
|---|---|
| Auto-submit applications | Legal/ethical — draft only |
| Mobile app | CLI/terminal-native skill |
| Email notifications | Manual/cron invocation |
| Multi-user SaaS | Personal tool, Phase 4 |
| Browser extension | G-Stack IS the browser layer |
| Cloudflare Workers deployment | Not needed — runs locally |
| Interview prep module | Phase 3 |
| Salary negotiation | Phase 3 |

## What Already Exists (Reused)

| Existing | How Used |
|---|---|
| G-Stack browse binary | LinkedIn scraping, custom pages, cookie management |
| G-Stack cookie-import-browser | LinkedIn authentication |
| Greenhouse public API | 4,516 companies, no browser needed |
| Lever public API | 947 companies, no browser needed |
| Workday API patterns | 3,493 companies via community-discovered endpoints |
| awesome-easy-apply repo | 800+ companies with metadata |
| job-board-aggregator repo | 9,456 company slugs + scraper patterns |
| Cloudflare Crawl API | Career URL discovery for non-ATS companies |
| User's aditya_resume.tex | Design reference + initial profile extraction |

---

## Eng Review Completion Summary

```
+====================================================================+
|              ENG REVIEW — COMPLETION SUMMARY                        |
+====================================================================+
| Step 0: Scope Challenge  | BIG CHANGE — restructured scraping arch  |
| Architecture Review      | 3 issues found, all resolved              |
|   - Company lists        | Embed community data (1A)                 |
|   - CF Crawl role        | URL discovery only (2A)                   |
|   - Scraper pattern      | Functions not classes (3B)                 |
| Code Quality Review      | 1 issue found                             |
|   - CF client location   | Dedicated cf_client.py (4A)               |
| Test Review              | Diagram produced, 0 gaps                  |
| Performance Review       | 2 issues found                            |
|   - Parallelization      | ThreadPoolExecutor 10 workers (5A)        |
|   - Daily scope          | Relevance-filtered 200-500 co (6A)        |
| NOT in scope             | written (8 items)                         |
| What already exists      | written (9 items reused)                  |
| Failure modes            | 14 mapped, 0 CRITICAL GAPS                |
| Unresolved decisions     | 0                                         |
+====================================================================+
```
