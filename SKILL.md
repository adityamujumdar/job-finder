# JobHunter AI — Claude Skill

## Trigger
User says any of: "find me jobs", "job search", "find jobs", "run jobhunter", "daily report", "show jobs"

## Setup (first time only)
```bash
cd /Users/adityamujumdar/projects/job-finder
source .venv/bin/activate
```

## Pipeline
Run these in sequence:

### Step 1: Scrape (download 502K+ jobs + live scrape preferred companies)
```bash
python -m src.scraper
```
Options: `--skip-download` (use cached JBA), `--skip-live` (no live scrape), `--live-only`

### Step 2: Match (score all jobs against profile)
```bash
python -m src.matcher
```
Options: `--min-score 50` (only P1-P3), `--date YYYY-MM-DD`

### Step 3: Report (generate CSV + summary)
```bash
python -m src.report
```
Options: `--top 30` (show more), `--date YYYY-MM-DD`

## How to Present Results
1. Read the terminal summary from Step 3
2. Present the P1 count prominently: "Found X P1 jobs — apply today!"
3. Show top 5-10 P1 matches with title, company, location, score
4. Mention P2 count: "Plus Y strong P2 matches worth applying this week"
5. Note any scrape failures from Step 1 output
6. Tell user: "Full report saved to data/reports/YYYY-MM-DD.csv"

## Profile Updates
User wants to change preferences:
```bash
# Edit config/profile.yaml directly
# Then re-run pipeline
```

## Quick Re-run (cached data)
If user wants a quick re-score without re-downloading:
```bash
python -m src.scraper --skip-download --skip-live
python -m src.matcher
python -m src.report
```

## Troubleshooting
- No jobs found → Check data/jobs/ has today's file
- Low P1 count → Suggest broadening target_roles in profile.yaml
- Scrape failures → Check internet connection, specific ATS may be down
