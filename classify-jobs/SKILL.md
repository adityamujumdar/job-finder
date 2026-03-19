---
name: classify-jobs
version: 2.0.0
description: |
  Classify scored job matches into APPLY NOW / APPLY THIS WEEK / STRETCH / SKIP
  using Claude as the LLM. Reads today's scored data and your profile, then ranks
  each candidate job against your background and gives a clear action for each.
---

# JobHunter AI — Classify Jobs

## Philosophy

Classify means **DO IT**. Don't summarize the buckets, don't explain the process —
classify the jobs and show the output. Only stop if there's no scored data to work with.

Read the FULL list before classifying anything. Skimming leads to false positives in
APPLY NOW and missed gems in P2. Every classification must be anchored in specific data —
title alignment, years of experience match, named skills — not vibes.

Borrowed from [gstack/retro](https://github.com/garrytan/gstack): anchor praise in
actual commits, frame growth suggestions as investment advice. Applied here: anchor every
classification in the actual job data, and frame SKIP/STRETCH decisions as information
not rejection. Borrowed from [gstack/review](https://github.com/garrytan/gstack):
read the full diff before commenting — read every job before bucketing any of them.

---

## Only stop for:
- Nothing. Fix every missing prerequisite automatically.

## Never stop for:
- Missing scored data — run the full pipeline inline (scraper → matcher → report → site)
- Missing profile.yaml — copy example and run profile setup
- Low P1 count (classify what's there, even if it's just 2 jobs)
- Jobs you've already classified (re-classify if asked — the user asked)
- Asking permission to move on to the next job

---

## Trigger
"classify jobs", "classify my P1 jobs", "rank these jobs", "which jobs should I apply to",
"which of these should I apply to first", "/classify-jobs"

---

## Step 0 — Prerequisite Check & Auto-Fix

**Fix everything automatically — never tell the user to "run /jobhunter first."**

```bash
# 1. Ensure .venv exists
if [ ! -d ".venv" ]; then
  echo "⚙️  Creating .venv..."
  python3 -m venv .venv && source .venv/bin/activate && pip install -q -r requirements.txt
  echo "✅ Environment ready"
else
  source .venv/bin/activate
fi

# 2. Ensure profile exists
if [ ! -f "config/profile.yaml" ]; then
  cp config/profile.yaml.example config/profile.yaml
  echo "⚙️  Created profile.yaml — will need to set up your profile first"
fi

# 3. gstack/browse check — ADVISORY (not blocking).
if [ -d "$HOME/.claude/skills/gstack" ] && [ -f "$HOME/.claude/skills/gstack/browse/bin/find-browse" ]; then
  echo "✅ gstack/browse available"
else
  echo "⚠️  gstack not installed — browse (fetching job descriptions from career pages) unavailable"
  echo "   To install: git clone https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup"
  echo "   Then add a 'gstack' section to CLAUDE.md that says to use /browse for all web browsing,"
  echo "   never use mcp__claude-in-chrome__* tools, and lists available skills:"
  echo "   /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,"
  echo "   /design-consultation, /review, /ship, /browse, /qa, /qa-only,"
  echo "   /design-review, /setup-browser-cookies, /retro, /debug, /document-release"
fi
```

```bash
# 3. Check for scored data — run the pipeline if missing
python3 -c "
import json, pathlib
today = __import__('datetime').date.today().isoformat()
path = pathlib.Path(f'data/scored/{today}.json')
if path.exists():
    jobs = json.loads(path.read_text())
    p1 = sum(1 for j in jobs if j.get('_priority') == 'P1')
    p2 = sum(1 for j in jobs if j.get('_priority') == 'P2')
    print(f'✅ {len(jobs)} jobs loaded — {p1} P1, {p2} P2')
else:
    print(f'⚙️  No scored data for {today} — running pipeline now...')
" 2>/dev/null
```

If scored data is missing: **run the pipeline automatically** before classifying:
```bash
python -m src.scraper --skip-live && python -m src.matcher && python -m src.report && python -m src.site_generator
```

If profile.yaml was just created from example: **run profile setup first** (ask the user what roles they're looking for, where they're based, etc. — same as `/jobhunter` Step 1), then run the pipeline, then classify.

---

## Step 0b — Non-JBA Job Support (Browse)

If the user provides specific job URLs that are NOT in the scored data (e.g., from company
career pages not covered by JBA like Scotiabank, government job boards, or specific listings
that weren't picked up), use gstack `/browse` to fetch the job description.

**First, check if gstack is available:**
```bash
BROWSE_OUTPUT=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)
if [ -z "$B" ]; then
  echo "BROWSE_NOT_AVAILABLE"
fi
```

**If gstack is available:**
```bash
$B goto <job_url>
$B text
```
Validate the output contains job description content before using it.

**If gstack is NOT available:** Use AskUserQuestion:
1. **"Install gstack now"** — Show:
   `git clone https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup`
   Then tell them to add a "gstack" section to CLAUDE.md that says to use /browse for all
   web browsing, never use mcp__claude-in-chrome__* tools, and lists available skills:
   /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
   /design-consultation, /review, /ship, /browse, /qa, /qa-only,
   /design-review, /setup-browser-cookies, /retro, /debug, /document-release.
   Then ask the user if they also want to add gstack to the current project so teammates get it.
   After installing, retry the browse.
2. **"I'll paste the job description"** — Accept pasted text.
3. **"Skip this job"** — Continue without it.

After fetching (via browse or paste), **score and save the browsed job:**

1. Extract from the text: `title`, `company`, `location`, `url`, `skill_level`.
2. Score it:
```bash
python3 -c "
from src.matcher import score_and_save_browsed
result = score_and_save_browsed({
    'title': 'REPLACE_TITLE',
    'company': 'REPLACE_COMPANY',
    'url': 'REPLACE_URL',
    'location': 'REPLACE_LOCATION',
    'skill_level': 'REPLACE_LEVEL',
})
print(f\"✅ {result['title']} @ {result['company']} → {result['_score']:.1f} ({result['_priority']})\")
"
```

The job is now in `data/scored/DATE.json` (tagged `_source: browse`) and will be included
in the candidate list automatically. Classify it using the same bucket criteria. Mark in output:
```
🌐 (Browsed — scored via pipeline, not from JBA)
```

---

## Step 1 — Load Candidates

Load P1 jobs. If fewer than 5 P1 jobs, also include the top P2 jobs (up to 30 total):

```bash
python3 -c "
import json, pathlib
today = __import__('datetime').date.today().isoformat()
jobs = json.loads(pathlib.Path(f'data/scored/{today}.json').read_text())
p1 = [j for j in jobs if j.get('_priority') == 'P1']
p2 = [j for j in jobs if j.get('_priority') == 'P2']
candidates = p1 if len(p1) >= 5 else (p1 + p2[:30 - len(p1)])
tier = 'P1' if len(p1) >= 5 else f'P1 + top P2 (only {len(p1)} P1 today)'
print(f'Classifying {len(candidates)} {tier} jobs')
print(json.dumps(candidates[:30], indent=2))
"
```

---

## Step 2 — Read Profile

```bash
cat config/profile.yaml
```

Note: `target_roles`, `skills`, `target_level`, `years_experience`, `location`, `preferred_companies`.
These are the facts your classifications must be anchored in.

---

## Step 3 — Read ALL Jobs Before Classifying Any

Before assigning any bucket, read every job in the list. You are looking for:
- Which titles are exact matches vs partial matches vs false positives
- Which companies are real product companies vs staffing farms
- Which required skills you have vs gaps
- Level alignment (title says "Senior" — does the JD confirm it?)

**NEVER classify the first job until you've read the last job.**
This prevents APPLY NOW inflation and catches the real gems buried in the list.

---

## Step 4 — Classify Each Job

For each job, read title + company + description (if available), then assign a bucket.
Every classification must include a one-line reason anchored in actual data.

### Bucket Definitions

| Bucket | Criteria |
|--------|----------|
| **🎯 APPLY NOW** | Title ✅ + core skills ✅ + level ✅ + real product company ✅. No meaningful gaps. |
| **📅 APPLY THIS WEEK** | Strong match with exactly one manageable gap (1 missing skill, slight level mismatch). |
| **⚡ STRETCH** | Interesting but meaningfully underqualified. Apply only if excited — a reach, not a waste. |
| **⏭️ SKIP** | Wrong function, staffing firm, expired listing, or score is a false positive. |

### Skill gap analysis (mandatory per job)

For every job classified as APPLY NOW, APPLY THIS WEEK, or STRETCH, include a skill tag line
showing which of your skills match and which are gaps:

```
Skills: ✅ SQL  ✅ Python  ✅ Tableau  ⚠️ dbt (nice-to-have)  ❌ Go (required)
```

- ✅ = you have it and they want it
- ⚠️ = they mention it but it's learnable / nice-to-have
- ❌ = they require it and you don't have it (disqualifying gap)

Only list skills relevant to the specific job description. Don't pad with irrelevant matches.
For SKIP jobs, a skill line is optional — the SKIP reason is sufficient.

### Anchor rules (from gstack/retro: "anchor praise in actual commits")

- ✅ "Scores 97.9 — your SQL + Tableau background matches their required tools exactly" → valid
- ✅ "SKIP — title says 'Data Engineer' but description is Kubernetes + SRE, wrong function" → valid
- ❌ "Strong match" → too vague, must anchor in a specific data point
- ❌ "Good company, worth applying" → no data, not a classification

### APPLY NOW gate (must pass ALL four):
1. Title is genuinely in `target_roles` (phrase-level, not token-bag)
2. At least 2 of your top 3 skills appear in the JD
3. Level is within one step of `target_level`
4. Company is a real product company (not recruiter, not staffing, not "data center")

### SKIP signals — DO NOT flag as APPLY NOW:
- "data center", "infrastructure", "SRE", "DevOps" in description for a data/analytics role
- Company name contains "Solutions", "Staffing", "Resources", "Consulting", "Global HR"
- Job posted by a third-party recruiter, not the company itself
- Requires 10+ years when you have significantly fewer (not a stretch, a mismatch)
- Title says one thing, description says another (keyword stuffing / false positive)
- Remote listing but buried note says "must be onsite 5 days" — misrepresented role

### Suppressions — DO NOT flag these (from gstack/review philosophy):
- STRETCH for 1-2 skill gaps that are learnable on the job (learnable ≠ disqualifying)
- APPLY THIS WEEK for companies you're not excited about (still valuable signal)
- SKIP for reach roles — frame as information, not rejection

---

## Step 5 — Output

Lead with the headline count, then the classified list:

```
🎯 APPLY NOW (tonight):
  #a3f9c1d2  Netflix Analytics Engineer        Remote   97.9
    — SQL + Tableau, exact level match
    — Skills: ✅ SQL  ✅ Python  ✅ Tableau  ✅ Analytics
  #b2c1d3e4  Anthropic Data Analyst            SF       92.8
    — Python + BI, mission-driven company
    — Skills: ✅ Python  ✅ SQL  ✅ BI  ⚠️ dbt (nice-to-have)

📅 APPLY THIS WEEK:
  #c4d5e6f7  Stripe BI Analyst                 Remote   85.2
    — Strong fit; dbt gap (learnable)
    — Skills: ✅ SQL  ✅ Python  ⚠️ dbt (learnable)  ⚠️ Looker (similar to Tableau)
  #d6e7f8a9  Linear Data Engineer              Remote   83.1
    — Solid match; uses Go (you know Python)
    — Skills: ✅ SQL  ✅ Python  ❌ Go (required)

⚡ STRETCH (apply if excited):
  #e8f9a0b1  OpenAI Research Analyst           SF       78.1
    — Heavy ML context; worth trying if mission resonates
    — Skills: ✅ Python  ✅ SQL  ❌ PyTorch (required)  ❌ ML pipelines (required)

⏭️ SKIP:
  #f1a2b3c4  Acme Corp Data Infrastructure     Remote   74.6  — SRE/Kubernetes, wrong function
  #a5b6c7d8  TechStaffing Data Lead            Remote   72.0  — Recruiter posting, not a real company
```

Then write 2-3 sentences of honest analysis (not cheerleading):
- Which buckets are well-populated vs thin
- One honest observation: "Most P1s are at fintech companies — if you haven't researched the sector, worth 30 min before applying"
- One leveling-up note if there's a pattern in the gaps: "dbt shows up in 4 of your APPLY THIS WEEK gaps — a weekend project would clear that signal"
  Frame gaps as investment, not criticism (from gstack/retro philosophy).

---

## Step 6 — Save Classification History

Save results to `.context/classification-history.json` (append, don't overwrite):

```json
{
  "date": "2026-03-16",
  "apply_now": [{"id": "a3f9c1d2", "title": "...", "company": "..."}],
  "apply_this_week": [...],
  "stretch": [...],
  "skip": [...],
  "common_skill_gap": "dbt",
  "total_classified": 12
}
```

If history exists: show one-line trend:
```
  vs last run (Mar 14): APPLY NOW 2→5 (↑3), common gap: dbt (consistent)
```

---

## Step 7 — Offer Next Action

After showing results, offer exactly one next step — the most valuable one given the output:

```
Want me to build a tailored resume for job #a3f9c1d2 (Netflix)?
→ Say "build resume for #a3f9c1d2" or use /tailor-resume
```

**One offer. Not a menu of 5 options.** (from gstack/ship: non-interactive by default)

---

## Looking Up a Job by ID

```bash
python3 -c "
import json, hashlib, pathlib
today = __import__('datetime').date.today().isoformat()
jobs = json.loads(pathlib.Path(f'data/scored/{today}.json').read_text())
jid = 'a3f9c1d2'  # replace with actual ID
match = next((j for j in jobs if hashlib.sha256(j.get('url','').encode()).hexdigest()[:8] == jid), None)
if match:
    print(f\"{match['title']} @ {match['company']}\")
    print(f\"URL: {match.get('url','')}\")
    print(f\"Score: {match.get('_score', 0):.1f}  Priority: {match.get('_priority','?')}\")
else:
    print('Job not found — may be from a different date')
    print('Check: ls data/scored/ for available dates')
"
```
