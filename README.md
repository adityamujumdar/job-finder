# 🎯 JobHunter AI

**Automated job discovery across 502K+ jobs from 12,000+ companies — scored, ranked, and delivered as a beautiful dashboard. Powered by Claude.**

[**→ Live Dashboard**](https://adityamujumdar.github.io/job-finder) · [Report Bug](https://github.com/adityamujumdar/job-finder/issues)

---

## What It Does

JobHunter AI downloads 502K+ job listings daily from 12,000+ companies across Greenhouse, Lever, Workday, Ashby, and BambooHR. It scores each job against your profile (target roles, location, skills, preferred companies) and publishes a prioritized dashboard to GitHub Pages.

**Then Claude becomes your personal recruiter** — classifying which jobs to apply to, tailoring your resume per position, and generating a beautiful HTML/PDF resume in seconds.

**No server. No cost. Fully automated.**

### Features

- 🔍 **502K+ jobs** from 12K+ companies, refreshed daily
- 📊 **Smart scoring** — title match, location, level, keywords, company preference, recency
- 🏷️ **Priority tiers** — P1 (apply now), P2 (this week), P3 (if time)
- 🔢 **Unique job IDs** — reference any job as `#a3f9c1d2` when talking to Claude
- ⭐ **"New Today"** badges — instantly see what's fresh
- 🔎 **Search & filter** — by title, company, location, ATS platform, priority
- 🌙 **Dark mode** — easy on the eyes
- 📱 **Mobile responsive** — job hunt from anywhere
- 🤖 **GitHub Actions** — runs daily, zero maintenance
- 🧠 **Claude intelligence** — classify, tailor resumes, analyze jobs conversationally

---

## How It Works

```
GitHub Actions (daily @ 8am UTC)
  1. Download 502K jobs from job-board-aggregator    (~15 seconds)
  2. Score each job against your profile              (~8 seconds)
  3. Generate static HTML dashboard                   (~1 second)
  4. Deploy to GitHub Pages                           (automatic)

You + Claude (on demand)
  5. "Classify my P1 jobs" → Claude ranks APPLY NOW / THIS WEEK / SKIP
  6. "Build resume for job #a3f9c1d2" → Claude tailors your resume to that job
  7. Beautiful HTML resume → Cmd+P → PDF in your browser
```

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  TIER 1: JBA Download (502K jobs, ~15s)                  │
│  src/downloader.py → data/jba/YYYY-MM-DD.json           │
├─────────────────────────────────────────────────────────┤
│  TIER 2: Live Scrape (preferred companies, ~2-5 min)     │
│  src/jba_fetcher.py → fresh data for target companies   │
├─────────────────────────────────────────────────────────┤
│  PIPELINE                                                │
│  src/scraper.py  → merge + dedup + clean + prune        │
│  src/matcher.py  → score + rank (P1/P2/P3)              │
│  src/report.py   → CSV + terminal summary               │
│  src/site_generator.py → static HTML dashboard          │
├─────────────────────────────────────────────────────────┤
│  CLAUDE INTELLIGENCE (SKILL.md)                          │
│  • Classify jobs: APPLY NOW / THIS WEEK / STRETCH / SKIP│
│  • Tailor resume per job (reads RESUME.md)               │
│  • Generate HTML resume → Cmd+P → PDF                   │
│  • LinkedIn scraping (via G-Stack, optional)            │
│  • LLM upgrade path: Ollama/DeepSeek (optional)         │
└─────────────────────────────────────────────────────────┘
```

---

## Setup

### 1. Fork & Clone

```bash
# Fork this repo on GitHub, then:
git clone https://github.com/YOUR_USERNAME/job-finder.git
cd job-finder
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Your Profile

```bash
cp config/profile.yaml.example config/profile.yaml
```

Edit `config/profile.yaml` with your details:

```yaml
name: "Your Name"
location: "City, ST"           # Where you're based
remote_ok: true
willing_to_relocate: true
relocation_cities:
  - "San Francisco, CA"
  - "New York, NY"

years_experience: 3            # Affects level matching
target_level: "mid"            # intern / junior / mid / senior / lead / manager

target_roles:
  - "Data Analyst"
  - "Business Intelligence"
  - "Analytics Engineer"

skills:
  - Python
  - SQL
  - Tableau
  - Power BI

boost_keywords:
  - analytics
  - reporting
  - dashboard

preferred_companies:
  greenhouse:
    - "anthropic"   # jobs.lever.co/anthropic → slug is "anthropic"
    - "stripe"
  workday:
    - "netflix|wd1|netflix"    # format: slug|instance|site_name
  ashby:
    - "1password"
```

> **Finding company slugs:** Search the seed files: `grep -i "netflix" data/seed/workday.json`

### 3. Set Up Your Resume (for Claude tailoring)

```bash
cp RESUME.md.example RESUME.md
```

Edit `RESUME.md` with your actual work experience, skills, and education. This file is **gitignored** (safe to put personal details). Claude reads it when building tailored resumes for specific jobs.

> **Note:** `RESUME.md` stays on your machine only — it's never committed to git.

### 4. Run the Pipeline Locally

```bash
source .venv/bin/activate
python -m src.scraper           # Download & merge 502K jobs (~25s)
python -m src.matcher           # Score & rank against your profile (~8s)
python -m src.report            # CSV report + terminal summary
python -m src.site_generator    # Generate HTML dashboard
open site/index.html            # View your dashboard
```

### 5. Deploy to GitHub Pages

1. Push your fork to GitHub
2. Go to repo **Settings → Pages → Source: GitHub Actions**
3. The workflow (`.github/workflows/daily.yml`) will run daily at 8am UTC

Your dashboard will be live at `https://YOUR_USERNAME.github.io/job-finder`

---

## Using Claude as Your Job-Hunting AI

Load **SKILL.md** into Claude (or use it as a Claude Project Knowledge file). Then talk to Claude naturally:

### Run the full pipeline
> "Find me jobs" → Claude runs scraper → matcher → report → dashboard

### Classify your matches
> "Classify my P1 jobs" → Claude reads your scored data and sorts into APPLY NOW / THIS WEEK / STRETCH / SKIP

### Reference jobs by ID
Every job card shows a unique `#a3f9c1d2` ID. Use it to talk about specific jobs:
> "Tell me about job #a3f9c1d2" → Claude looks it up and gives you a full analysis
> "Build resume for job #a3f9c1d2" → Claude tailors your resume to that exact role

### Get a tailored resume
> "Build me a resume for the Netflix Analytics Engineer role" → Claude reads RESUME.md + the job description → generates a beautiful HTML resume → you open it and Cmd+P → PDF

### Analyze a specific job
> "Tell me about this job: [paste URL]" → Claude reads the description and tells you what matches, what's missing, and whether to apply

### Update your profile
> "Update my profile to add dbt to my skills" → Claude edits config/profile.yaml and re-runs the pipeline

---

## Scoring Algorithm

| Factor | Weight | How It Works |
|--------|--------|-------------|
| Title Match | 35% | Phrase-level match vs target roles (not token bags — "Data Center Engineer" ≠ "Data Analyst") |
| Location | 20% | Exact city (1.0) → metro (0.95) → state (0.8) → relocation (0.7) → remote (1.0) |
| Level | 15% | Exact match (1.0) → one-off (0.7) → two-off (0.3) |
| Keywords | 15% | Boost keywords found in title, normalized and capped at 1.0 |
| Company | 10% | Preferred company = 1.0, else 0.0 |
| Recency | 5% | Freshness: max(0, 1 - days/30) |

**Priority Tiers:** P1 (85-100, apply today), P2 (70-84, apply this week), P3 (50-69, apply if time)

---

## LLM Upgrade Path

| Scorer | Status | How |
|--------|--------|-----|
| **Claude** (default) | ✅ Works now | Load SKILL.md → "classify my P1 jobs" |
| **Ollama/DeepSeek** (local GPU) | 🔜 Planned | `src/llm_scorer.py` (not yet built) |

Claude is the default and primary intelligence layer. The local model path (for automated batch scoring of 5K candidates overnight on your GPU) is planned but not yet implemented.

---

## File Structure

```
job-finder/
├── config/
│   ├── profile.yaml          # YOUR preferences (edit this — in git)
│   └── profile.yaml.example  # Template for new users
├── src/
│   ├── scraper.py            # Orchestrator: download + live scrape + merge
│   ├── matcher.py            # Score 502K jobs against your profile
│   ├── report.py             # CSV + terminal summary
│   ├── site_generator.py     # Static HTML dashboard
│   ├── downloader.py         # JBA bulk download
│   ├── jba_fetcher.py        # Live ATS scraping (vendored from JBA)
│   └── config.py             # Shared config loading
├── data/
│   ├── seed/                 # Company slugs per ATS (committed)
│   └── ...                   # Daily pipeline output (gitignored)
├── site/
│   └── index.html            # Generated dashboard (committed for GitHub Pages)
├── SKILL.md                  # Claude skill definition — load into Claude
├── RESUME.md                 # YOUR resume in Markdown (gitignored — personal)
├── RESUME.md.example         # Template: copy to RESUME.md and fill in
└── .github/workflows/
    └── daily.yml             # GitHub Actions: runs pipeline daily
```

---

## Credits & Attribution

Built on the shoulders of:

- **[job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator)** (MIT License) — The data backbone. Scrapes 502K+ jobs daily from Greenhouse, Lever, Workday, Ashby, and BambooHR. Our `src/jba_fetcher.py` is vendored from their scraper.

- **[awesome-easy-apply](https://github.com/nickmccullum/awesome-easy-apply)** — Company metadata (791 companies with descriptions, slugs, and LinkedIn URLs).

---

## Cost

| Resource | Cost |
|----------|------|
| Job data | Free (JBA open data on GitHub) |
| Hosting | Free (GitHub Pages) |
| Pipeline | Free (GitHub Actions, ~2 min/day) |
| Claude intelligence | Free (within your Claude plan) |
| **Total** | **$0/month** |

---

## License

[MIT](LICENSE) — Fork it, customize it, help people find jobs.

---

*Built for job seekers, by job seekers. If this helps you land a role, star the repo ⭐*
