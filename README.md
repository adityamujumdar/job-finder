# 🎯 JobHunter AI

**Automated job discovery across 502K+ jobs from 12,000+ companies — scored, ranked, and delivered as a beautiful dashboard.**

[**→ Live Dashboard**](https://adityamujumdar.github.io/job-finder) · [Report Bug](https://github.com/adityamujumdar/job-finder/issues)

---

## What It Does

JobHunter AI downloads 502K+ job listings daily from 12,000+ companies across Greenhouse, Lever, Workday, Ashby, and BambooHR. It scores each job against your profile (target roles, location, skills, preferred companies) and publishes a prioritized dashboard to GitHub Pages.

**No server. No cost. Fully automated.**

### Features

- 🔍 **502K+ jobs** from 12K+ companies, refreshed daily
- 📊 **Smart scoring** — title match, location, level, keywords, company preference, recency
- 🏷️ **Priority tiers** — P1 (apply now), P2 (this week), P3 (if time)
- ⭐ **"New Today"** badges — instantly see what's fresh
- 🔎 **Search & filter** — by title, company, location, priority
- 🌙 **Dark mode** — easy on the eyes
- 📱 **Mobile responsive** — job hunt from anywhere
- 🤖 **GitHub Actions** — runs daily, zero maintenance

## How It Works

```
GitHub Actions (daily @ 8am UTC)
  1. Download 502K jobs from job-board-aggregator    (~15 seconds)
  2. Score each job against your profile              (~8 seconds)
  3. Generate static HTML dashboard                   (~1 second)
  4. Deploy to GitHub Pages                           (automatic)
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
└─────────────────────────────────────────────────────────┘
```

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/adityamujumdar/job-finder.git
cd job-finder
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Your Profile

Edit `config/profile.yaml` with your preferences:

```yaml
name: "Your Name"
location: "City, ST"
remote_ok: true
target_roles:
  - "Data Analyst"
  - "Business Intelligence"
  - "Analytics Engineer"
skills: [Python, SQL, Tableau]
boost_keywords: [analytics, data, reporting]
preferred_companies:
  greenhouse:
    - "anthropic"
    - "stripe"
```

See `config/profile.yaml.example` for the full template.

### 3. Run the Pipeline

```bash
# Full pipeline (download + score + report + site)
source .venv/bin/activate
python -m src.scraper           # Download & merge jobs
python -m src.matcher           # Score & rank
python -m src.report            # CSV report
python -m src.site_generator    # Generate HTML dashboard

# Open the dashboard locally
open site/index.html
```

### 4. Deploy to GitHub Pages

Push to GitHub, then enable Pages in repo settings (source: GitHub Actions).
The included workflow (`.github/workflows/daily.yml`) will:
- Run the pipeline daily at 8am UTC
- Generate and deploy the dashboard automatically

## Scoring Algorithm

| Factor | Weight | How It Works |
|--------|--------|-------------|
| Title Match | 35% | Containment + Jaccard similarity vs target roles |
| Location | 20% | Exact city (1.0) → metro (0.95) → state (0.8) → relocation (0.7) → remote (1.0) |
| Level | 15% | Exact match (1.0) → one-off (0.7) → two-off (0.3) |
| Keywords | 15% | Boost keywords found in title, normalized |
| Company | 10% | Preferred company = 1.0, else 0.0 |
| Recency | 5% | Freshness: max(0, 1 - days/30) |

**Priority Tiers:** P1 (85-100), P2 (70-84), P3 (50-69)

## Credits & Attribution

This project is built on the shoulders of:

- **[job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator)** (MIT License) — The data backbone. Scrapes 502K+ jobs daily from Greenhouse, Lever, Workday, Ashby, and BambooHR. Our `src/jba_fetcher.py` is vendored from their scraper. Our bulk data download comes from their daily GitHub data publications.

- **[awesome-easy-apply](https://github.com/nickmccullum/awesome-easy-apply)** — Company metadata (791 companies with descriptions, slugs, and LinkedIn URLs). Used for seed data enrichment.

## Cost

| Resource | Cost |
|----------|------|
| Job data | Free (JBA open data on GitHub) |
| Hosting | Free (GitHub Pages) |
| Pipeline | Free (GitHub Actions, ~2 min/day) |
| **Total** | **$0/month** |

## License

[MIT](LICENSE) — Use it, fork it, help people find jobs.

---

*Built for job seekers, by job seekers. If this helps you land a role, star the repo ⭐*
