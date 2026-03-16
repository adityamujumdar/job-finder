---
name: jobhunter
version: 2.0.0
description: |
  Full job-hunting pipeline: download 502K+ jobs, score against your profile,
  generate a ranked dashboard, classify matches, and run the company router.
  For resume tailoring use /tailor-resume. For classification only use /classify-jobs.
---

# JobHunter AI — Full Pipeline

## Philosophy

You are not a passive tool — you are the user's job-hunting AI. When someone says
"find me jobs" or `/jobhunter`, that means **DO IT**. Run the pipeline straight through
and show results. Only stop when a blocking issue actually prevents progress.

Zero silent failures: every error is visible. Lead with the number: the first thing the
user sees should be the headline — not logs, not setup noise, not warnings. Terse.

Borrowed from [gstack](https://github.com/garrytan/gstack): non-interactive by default,
read full context before acting, anchor every output in actual data, save history for
trend tracking, frame gaps as leveling-up opportunities not failures.

---

## Only stop for:
- `config/profile.yaml` missing (can't score without a profile)
- `.venv` missing and `pip install` fails
- Network is down and JBA download fails after retry
- Scored data is 0 jobs (something went wrong — show the error)

## Never stop for:
- Stale cached data (use it, note its age)
- Some companies failing to live-scrape (report them, continue with what succeeded)
- Warnings in scraper output (log them, don't surface to user)
- P1 count being lower than expected (show what's there, let user tune profile)

---

## Trigger
"find me jobs", "job search", "run jobhunter", "daily report", "show jobs",
"set up my profile", "update profile", "what's new today", "/jobhunter"

---

## Step 0 — Prerequisite Check

Run this check first, every time. Do not proceed if it fails.

```bash
echo "=== JobHunter AI — Prerequisite Check ==="
# Python environment
[ -d ".venv" ] && echo "✅ .venv found" || echo "❌ .venv missing — run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
[ -f "config/profile.yaml" ] && echo "✅ profile.yaml found" || echo "❌ No profile — type /jobhunter and Claude will set it up for you"
[ -f "RESUME.md" ] && echo "✅ RESUME.md found" || echo "⚠️  No RESUME.md — run: cp RESUME.md.example RESUME.md (needed for resume tailoring)"
```

```bash
# Profile staleness check — detect if profile changed since last score.
# If stale, the matcher step below will rescore automatically.
python3 -c "
import json, sys
from src.config import profile_hash, SCORED_DIR, today
meta_path = SCORED_DIR / f'{today()}.meta.json'
if not meta_path.exists():
    print('ℹ️  No scored data yet — will score fresh')
    sys.exit(0)
meta = json.load(open(meta_path))
current = profile_hash()
if meta.get('profile_hash') != current:
    print(f'⚠️  Profile changed since last score (was {meta[\"profile_hash\"]}, now {current}). Will rescore.')
else:
    print(f'✅ Profile hash: {current} (matches scored data)')
" 2>/dev/null || echo "⚠️  Could not check profile staleness — will rescore to be safe"
```

If profile.yaml is missing: offer to set up the profile now (see Profile Setup below).
If .venv is missing: show the fix and stop.
If only RESUME.md is missing: continue with a warning — pipeline still works, tailoring won't.
If profile staleness check shows ⚠️: proceed with the pipeline — Step 2 (matcher) will regenerate scored data and the new `.meta.json` against the current profile.

---

## Step 1 — Profile Setup (first-time or "update profile" trigger)

When user asks to set up or update their profile:

1. Read `config/profile.yaml` if it exists — understand current state
2. Ask these questions one at a time (never batch — one AskUserQuestion per question):
   - "What kind of roles are you looking for?" (e.g. Software Engineer, Data Analyst)
   - "Where are you based? Open to remote or relocation?"
   - "How many years of experience do you have?"
   - "Any specific companies you'd love to work at?"
3. Show proposed `profile.yaml` contents and confirm before writing
4. Re-run the pipeline after saving

**NEVER write profile.yaml without showing the user what you're about to write.**
**NEVER ask all questions at once — one at a time, like a conversation.**

---

## Step 2 — Setup

```bash
cd <your-project-directory>
source .venv/bin/activate
```

---

## Step 3 — Core Pipeline

Run straight through. Only surface errors that block completion.

### Scrape
```bash
python -m src.scraper              # full: JBA download (~15s) + live scrape preferred companies
python -m src.scraper --skip-live  # fast: JBA download only (~15s, skip live scrape)
```

### Match
```bash
python -m src.matcher   # score all jobs against profile (~8s, 502K jobs)
# Also writes data/scored/DATE.meta.json with profile fingerprint for staleness detection
```

### Report
```bash
python -m src.report    # CSV + terminal summary
```

### Dashboard
```bash
python -m src.site_generator
open site/index.html    # each job card shows a unique #xxxxxxxx job ID
```

---

## Step 4 — Company Intelligence Router

When user mentions a specific company, check which channel it's on before scraping:

```bash
grep -il "<company>" data/seed/greenhouse.json data/seed/lever.json \
  data/seed/workday.json data/seed/ashby.json data/seed/bamboohr.json
```

| Company | ATS | Notes |
|---------|-----|-------|
| Netflix | Workday ✅ | JBA download already has it — no live scrape needed |
| Anthropic | Greenhouse ✅ | JBA download + live scrape (`anthropic`) |
| Stripe | Greenhouse ✅ | JBA download + live scrape (`stripe`) |
| OpenAI | Greenhouse ✅ | JBA download + live scrape (`openai`) |
| Google, Apple, Amazon, Microsoft, Meta | ❌ not in JBA | LinkedIn / careers page |

**If not in JBA:** offer LinkedIn scrape or direct careers page browse via G-Stack.
**If >2,000 jobs at one company:** verify it's not a staffing farm before including.

---

## Step 5 — Present Results

Lead with the headline, every time:

```
🎯 Found {P1} P1 jobs — apply today!  +  {P2} P2 jobs worth applying this week.
```

Then show top 5-10 P1 matches in this format:
```
  #a3f9c1d2  Senior Software Engineer @ Stripe       SF · 93.2 · 3d ago
  #b7e2f4a9  Backend Engineer @ Anthropic             SF · 91.7 · 1d ago
  #c9d1e2f3  Staff Engineer @ Linear                  Remote · 88.4 · 2d ago
```

Anchor every claim in actual data:
- "Stripe scores 93.2 because your Python + distributed systems background matches their exact keywords" → good
- "Stripe is a strong match" → too vague, cut it

Then mention:
- P2 count and best 2-3 examples
- Report saved at `data/reports/YYYY-MM-DD.csv`
- Dashboard at `site/index.html`

End with an offer:
> "Want me to classify these and rank which to apply to first? → `/classify-jobs`"

---

## Step 6 — Save Pipeline History

After every successful run, append to `.context/jobhunter-history.json`:

```json
{
  "date": "2026-03-16",
  "p1": 51,
  "p2": 1175,
  "p3": 6773,
  "new_today": 48,
  "top_p1": [
    { "id": "a3f9c1d2", "title": "Senior Software Engineer", "company": "Stripe", "score": 93.2 }
  ],
  "pipeline_seconds": 25
}
```

If `.context/jobhunter-history.json` exists: load it and show a one-line trend:
```
  vs yesterday: P1 51 (↑8), P2 1175 (↓23), 48 new jobs added
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No P1 jobs | Broaden `target_roles` in profile.yaml — run: `/jobhunter update profile` |
| Zero jobs total | Re-run `python -m src.scraper` — JBA download may have failed |
| Scrape failures | Check internet; specific ATS may be temporarily down — noted in report |
| Netflix not showing | Already in JBA download — no live scrape needed for Workday companies |
| Stale data | Run with `--skip-live` for speed, or full scrape for freshness |

---

## Quick Re-run (cached data, no network)

```bash
python -m src.scraper --skip-download --skip-live
python -m src.matcher && python -m src.report && python -m src.site_generator
```
