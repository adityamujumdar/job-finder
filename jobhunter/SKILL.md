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
- No resume found (no RESUME.md and no .pdf in project root) — ask user to add one
- Network is down and JBA download fails after retry
- Scored data is 0 jobs (something went wrong — show the error)

## Never stop for:
- Missing `.venv` — create it and install deps automatically
- Missing `config/profile.yaml` — copy the example and run profile setup
- Missing `RESUME.md` when a PDF resume exists in the directory (use the PDF)
- Stale cached data (use it, note its age)
- Some companies failing to live-scrape (report them, continue with what succeeded)
- Warnings in scraper output (log them, don't surface to user)
- P1 count being lower than expected (show what's there, let user tune profile)

---

## Trigger
"find me jobs", "job search", "run jobhunter", "daily report", "show jobs",
"set up my profile", "update profile", "what's new today", "/jobhunter"

---

## Step 0 — Prerequisite Check & Auto-Fix

Run this check first, every time. **Fix everything automatically — never tell the user to do it themselves.**

```bash
echo "=== JobHunter AI — Prerequisite Check ==="

# 1. Python environment — create if missing
if [ ! -d ".venv" ]; then
  echo "⚙️  Creating .venv..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -r requirements.txt
  echo "✅ .venv created and dependencies installed"
else
  echo "✅ .venv found"
  source .venv/bin/activate
fi

# 2. Profile — copy example if missing (profile setup will customize it in Step 1)
if [ ! -f "config/profile.yaml" ]; then
  cp config/profile.yaml.example config/profile.yaml
  echo "⚙️  Created config/profile.yaml from example — will customize in profile setup"
else
  echo "✅ profile.yaml found"
fi

# 3. Resume check — BLOCKING. Pipeline requires a resume on file.
#    Checks for RESUME.md or any PDF in the project root.
RESUME_FOUND=false
if [ -f "RESUME.md" ]; then
  echo "✅ RESUME.md found"
  RESUME_FOUND=true
elif ls *.pdf 1>/dev/null 2>&1; then
  PDF_NAME=$(ls *.pdf | head -1)
  echo "✅ Resume PDF found: $PDF_NAME"
  RESUME_FOUND=true
else
  echo "❌ No resume found (need RESUME.md or a .pdf in this directory)"
  echo "   → Add your resume before running the pipeline."
  echo "   → Options: copy a PDF here, or create RESUME.md from the example:"
  echo "     cp RESUME.md.example RESUME.md && open RESUME.md"
fi
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

If profile.yaml was just created from example: proceed to Step 1 (Profile Setup) to customize it.
If profile staleness check shows ⚠️: proceed with the pipeline — the matcher will rescore against the current profile.
**If no resume was found (RESUME_FOUND=false):** Stop and use AskUserQuestion to ask the user to add their resume. Offer these options:
1. **"Point me to your resume file"** — User gives a path. Read and convert to RESUME.md.
2. **"I'll paste it here"** — User pastes text. Write to RESUME.md.
3. **"I have a PDF I'll drop in this folder"** — Tell them to add a .pdf and re-run.
**Do NOT proceed with the pipeline until a resume is present.**
**For all other issues: never stop. Never tell the user to "run X first." Fix it and keep going.**

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

## Step 5b — False Positive Detection & Negative Pattern Suggestions

After showing results, scan the P1 list for clusters of roles that look like false positives.
A false positive cluster is 3+ P1 jobs sharing a title pattern that doesn't match the user's
actual target function (e.g., "Cloud Platform Engineer" appearing in a Backend SWE search).

```python
# Pseudocode for cluster detection:
# 1. Group P1 jobs by 2-word title prefix (e.g., "Cloud Platform", "DevOps Engineer")
# 2. Any group with 3+ jobs where the prefix is NOT in target_roles → suggest exclusion
```

If false positive clusters are found, offer to add them as exclude_title_patterns:

```
⚠️  I noticed 6 P1 jobs are "Cloud Platform Engineer" roles — these look like
infrastructure/DevOps, not backend SWE. Want me to exclude these from future runs?

→ This would add `exclude_title_patterns: ["cloud platform"]` to your profile.
```

Use AskUserQuestion with options:
- **"Yes, exclude those"** — Add to profile.yaml `exclude_title_patterns` and rescore
- **"No, keep them"** — Leave as-is
- **"Let me pick which to exclude"** — Show the list and let user choose

After updating, re-run the matcher and show updated counts:
```bash
python -m src.matcher && python -m src.report
```

---

## Step 5c — Non-JBA Job Support (Browse)

If the user provides specific job URLs that are NOT in the scored results (e.g., jobs from
company career pages not covered by JBA like Scotiabank, or specific listings that weren't
picked up), use gstack browse to fetch the job description:

```bash
# Setup browse (one-time)
BROWSE_OUTPUT=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)

# Fetch the job description
$B goto <job_url>
$B text
```

If browse is not available, ask the user to paste the job description.

After fetching, present the job alongside the scored results with a note:
```
📌 Manual addition (not in JBA):
   Backend Software Engineer @ Scotiabank  Toronto · (manual — not scored)
   URL: https://jobs.scotiabank.com/...
```

Then offer: "Want me to classify this job or tailor your resume for it? → `/classify-jobs` or `/tailor-resume`"

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
