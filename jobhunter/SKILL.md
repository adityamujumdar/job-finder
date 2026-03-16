---
name: jobhunter
version: 1.0.0
description: |
  Full job-hunting pipeline: download 502K+ jobs, score against your profile,
  generate a ranked dashboard, classify matches, and run the company router.
  For resume tailoring use /tailor-resume. For classification only use /classify-jobs.
---

# JobHunter AI — Full Pipeline

## Trigger
"find me jobs", "job search", "run jobhunter", "daily report", "show jobs",
"set up my profile", "update profile", "what's new today", "/jobhunter"

## First-Time Setup Check
```bash
[ -f "RESUME.md" ]           || echo "❌ Run: cp RESUME.md.example RESUME.md  (then fill in your info)"
[ -f "config/profile.yaml" ] || echo "❌ Run: cp config/profile.yaml.example config/profile.yaml  (then fill in your info)"
[ -f "RESUME.md" ] && [ -f "config/profile.yaml" ] && echo "✅ Ready"
```
If either file is missing, stop and direct the user to README.md → Setup section.

## Setup
```bash
cd <your-project-directory>
source .venv/bin/activate
```

---

## 🎯 Core Pipeline

### Step 1 — Scrape
```bash
python -m src.scraper              # full: download 502K + live scrape preferred companies
python -m src.scraper --skip-live  # fast: download only (~25s)
```

### Step 2 — Match
```bash
python -m src.matcher   # score all jobs against profile (~8s)
```

### Step 3 — Report
```bash
python -m src.report    # CSV + terminal summary
```

### Step 4 — Dashboard
```bash
python -m src.site_generator
open site/index.html    # Each job card shows a unique #xxxxxxxx ID
```

---

## 🏢 Company Intelligence Router

When user mentions a specific company:

```bash
grep -il "<company>" data/seed/greenhouse.json data/seed/lever.json \
  data/seed/workday.json data/seed/ashby.json data/seed/bamboohr.json
```

| Company | ATS | Channel |
|---------|-----|---------|
| Netflix | Workday ✅ | JBA download + live scrape (`netflix\|wd1\|netflix`) |
| Anthropic | Greenhouse ✅ | JBA download + live scrape (`anthropic`) |
| Stripe | Greenhouse ✅ | JBA download + live scrape (`stripe`) |
| OpenAI | Greenhouse ✅ | JBA download + live scrape (`openai`) |
| Google, Apple, Amazon, Microsoft, Meta | ❌ not in JBA | LinkedIn / careers page |

**If not in JBA:** offer LinkedIn scrape or direct careers page browse via G-Stack.
**If >2,000 jobs:** verify it's not a staffing farm before including.

---

## 🧠 Profile Setup

When user wants to set up or update their profile:
1. Read `config/profile.yaml` — understand current format
2. Ask: role, years experience, skills, location, remote preference, target companies
3. Show proposed YAML and confirm before writing
4. Re-run pipeline after saving

---

## 📊 Presenting Results

1. Lead with P1 count: **"Found X P1 jobs — apply today!"**
2. Show top 5-10 P1 matches: job ID, title, company, location, score
3. Mention P2: "Plus Y strong P2 matches worth applying this week"
4. Report: `data/reports/YYYY-MM-DD.csv`
5. Dashboard: `site/index.html`
6. Offer: "Want me to classify these and build a resume for the best match?"
   → Use `/classify-jobs` or `/tailor-resume`

## Quick Re-run (cached)
```bash
python -m src.scraper --skip-download --skip-live
python -m src.matcher && python -m src.report && python -m src.site_generator
```

## Troubleshooting
- **No jobs** → re-run `python -m src.scraper`
- **Low P1 count** → broaden `target_roles` in `config/profile.yaml`
- **Scrape failures** → check internet; ATS may be temporarily down
