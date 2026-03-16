# JobHunter AI — Claude Skill

## Trigger
User says any of: "find me jobs", "job search", "find jobs", "run jobhunter", "daily report",
"show jobs", "set up my profile", "update profile", "apply to", "tailor resume",
"build resume for job", "classify jobs", "rank these jobs", "tell me about job #"

## First-Time Setup Check
Before doing anything, verify the user has configured their personal files:
```bash
# Check required files exist
[ -f "RESUME.md" ] && echo "✅ RESUME.md found" || echo "❌ RESUME.md missing — run: cp RESUME.md.example RESUME.md"
[ -f "config/profile.yaml" ] && echo "✅ profile.yaml found" || echo "❌ profile.yaml missing — run: cp config/profile.yaml.example config/profile.yaml"
```
If either is missing, stop and tell the user to follow the setup steps in README.md before continuing.

## Setup (first time only)
```bash
cd <your-project-directory>   # wherever you cloned job-finder
source .venv/bin/activate
```

---

## 🎯 Core Pipeline

### Step 1: Scrape (download 502K+ jobs + optional live scrape)
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

### Step 4: Generate Dashboard (static HTML site)
```bash
python -m src.site_generator
```
Options: `--date YYYY-MM-DD`
Opens: `site/index.html` — dashboard with search, filters, dark mode

---

## 🏢 Company Intelligence Router

When a user mentions a company they want to work at, Claude MUST determine the right channel:

### Step 1: Check ATS Platform
```bash
# Search all seed files for the company
grep -il "companyname" data/seed/greenhouse.json data/seed/lever.json data/seed/workday.json data/seed/ashby.json data/seed/bamboohr.json
```

### Step 2: Route Based on Result

**If found in seed data (e.g., Greenhouse):**
1. Tell user: "Stripe is on Greenhouse (slug: stripe)"
2. Add to `config/profile.yaml` under `preferred_companies.greenhouse`
3. Run pipeline with live scrape: `python -m src.scraper` (will fetch fresh data)
4. Present results filtered to that company

**If NOT found in any seed data (e.g., Google, Apple, Amazon):**
1. Tell user: "Google uses their own career site, not a standard ATS in our database"
2. Offer options:
   a. "I can search LinkedIn for Google BI jobs" → use LinkedIn scraping
   b. "I can check their careers page directly" → use G-Stack browse on careers.google.com
3. Add found jobs to pipeline with `ats: "linkedin"` or `ats: "direct"`

**If company has >2,000 jobs in JBA data:**
1. Might be a staffing farm — verify: "This company has 19,000 listings. Is this a staffing agency?"
2. If confirmed staffing → add to COMPANY_BLOCKLIST in `src/config.py`

### Known Big Tech Routing
| Company | Status | Best Channel |
|---------|--------|-------------|
| Google | NOT in JBA | LinkedIn / careers.google.com |
| Apple | NOT in JBA | LinkedIn / jobs.apple.com |
| Amazon | NOT in JBA | LinkedIn / amazon.jobs |
| Microsoft | NOT in JBA | LinkedIn / careers.microsoft.com |
| Meta | NOT in JBA | LinkedIn / metacareers.com |
| Netflix | Workday ✅ | JBA download + live scrape |
| Anthropic | Greenhouse ✅ | JBA download + live scrape |
| Stripe | Greenhouse ✅ | JBA download + live scrape |
| OpenAI | Greenhouse ✅ | JBA download + live scrape |
| NVIDIA | Workday ✅ | JBA download + live scrape |

---

## 🧠 Claude Intelligence Layer

### Conversational Profile Setup
When user wants to set up or update their profile:

1. **Ask about their background:**
   - Current role and years of experience
   - Target roles (be specific: "BI Analyst" vs generic "data")
   - Skills (languages, tools, platforms)
   - Location and remote preference
   - Companies they're interested in

2. **Generate profile.yaml:**
   Read the current `config/profile.yaml` to understand the format, then write the updated version.
   Required fields: `name`, `location`, `target_roles`, `skills`
   Important: `preferred_companies` need ATS-specific slugs:
   - Greenhouse: company slug from their careers URL (e.g., "anthropic" from jobs.lever.co/anthropic)
   - Workday: format is `slug|wd_instance|site_name` (e.g., "netflix|wd1|netflix")
   - Lever: company slug from lever.co URL
   - Ashby: company slug from jobs.ashby.io URL

3. **Confirm before saving:**
   Show the user the profile and ask for confirmation before writing.

4. **Re-run pipeline** after profile changes.

### Natural Language Job Filtering
When user asks about specific jobs (e.g., "show me remote BI roles", "what's at Netflix?"):

1. Read `data/scored/YYYY-MM-DD.json` (today's scored data)
2. Apply the user's natural language filter:
   - "remote" → filter for "remote" in location
   - "at Netflix" → filter for company == "netflix"
   - "BI roles" → filter for "business intelligence" or "bi" in title
   - "new today" → filter for jobs not in yesterday's scored data
   - "P1 only" → filter for _priority == "P1"
3. Present results as a formatted list with scores, titles, companies, and apply links
4. Offer to help apply (see Resume Tailoring below)

### Job Analysis
When user asks "tell me about this job" or shares a job URL:
1. Use G-Stack browse to visit the job URL and extract the full description
2. Analyze fit against the user's profile (read `config/profile.yaml` for their target roles and skills):
   - Matching skills ✅
   - Missing skills ❌
   - Experience match
   - Location/remote compatibility
3. Give an honest assessment: "Strong match because X, but you're missing Y"
4. Offer to tailor resume for this specific job

---

## 🔢 Job ID Reference System

Every job in the dashboard has a unique 8-character hex ID shown in small monospace text below each card (e.g., `#a3f9c1d2`). This ID is derived from the job URL and is stable across days as long as the job URL doesn't change.

**Finding a job by ID:**
```bash
python3 -c "
import json, hashlib, sys
data = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
job_id = sys.argv[1].lstrip('#')
for j in data:
    url = j.get('url', '')
    if hashlib.sha256(url.encode()).hexdigest()[:8] == job_id:
        print(f\"{j['title']} @ {j['company']}\")
        print(f\"Score: {j['_score']:.1f} | Priority: {j['_priority']}\")
        print(f\"Location: {j.get('location','')}\")
        print(f\"URL: {url}\")
        break
" a3f9c1d2
```

**When the user says:** "build resume for job a3f9c1d2" or "tell me about #a3f9c1d2":
1. Look up the job using the snippet above (pass the ID with or without `#`)
2. Browse to its URL for the full description
3. Proceed to Resume Tailoring or Job Analysis below

---

## 🤖 LLM Classifier — Claude (Primary) + Local Model (Optional Upgrade)

This is the intelligence layer that classifies whether a job is a genuine match beyond the rule-based score.

### Backend Comparison

| Backend | When to Use | How |
|---------|-------------|-----|
| **Claude** (default) | Always — available right now, no setup | Classify section below — Claude reads job data directly |
| **Ollama/DeepSeek** (optional) | When you want automated batch scoring of 5K jobs | Requires `ollama serve` + `src/llm_scorer.py` (see below) |

---

### 🟢 Claude Classifier (Default — Use This Now)

When the user says "classify jobs", "which jobs should I apply to first?", or "rank these P1 jobs":

**Step 1: Load the scored jobs**
```bash
python3 -c "
import json
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
p1 = [j for j in jobs if j.get('_priority') == 'P1']
# Fall back to P2 if no P1 jobs today
candidates = p1 if p1 else [j for j in jobs if j.get('_priority') == 'P2']
print(f'Classifying {len(candidates)} jobs (tier: {\"P1\" if p1 else \"P2 fallback\"})')
print(json.dumps(candidates[:20], indent=2))
"
```

**Step 2: Read the user's profile to understand their criteria**
```bash
cat config/profile.yaml
# Note: target_roles, skills, target_level, years_experience, location
```

**Step 3: For each candidate job, classify using these buckets:**
- **APPLY NOW** — Strong match: title ✅, core skills ✅, level ✅, company type ✅
- **APPLY THIS WEEK** — Good match with minor gaps (one missing skill, slight level mismatch)
- **STRETCH** — Worth applying if excited, but you're underqualified for some requirements
- **SKIP** — Wrong function, false positive (e.g., "data center engineer" in a BI search)

**Classification signals to look for in the job description:**
- ✅ APPLY NOW: Uses tools from your skills list (SQL, Python, Tableau/Looker/Power BI, etc.), mentions years of experience that matches yours, team/industry aligns with your background
- ⏭️ SKIP: Title contains BI keyword but description is actually SWE / DevOps / data infrastructure; requires skills not in your profile; is at a staffing/consulting firm

**Step 4: Output format**
```
🎯 APPLY NOW (today):
  #a3f9c1d2 — [Company] [Title] (score: 97.9) — [why it's a match]

📅 APPLY THIS WEEK:
  #c4d5e6f7 — [Company] [Title] (score: 85.2) — [fit summary, one gap]

⚡ STRETCH (apply if excited):
  #d6e7f8a9 — [Company] [Title] (score: 78.1) — [what you'd need to nail the interview]

⏭️ SKIP:
  #e8f9a0b1 — [Company] [Title] — [one-line reason: false positive / wrong level / etc.]
```

**After classification:** Offer to build a tailored resume for any APPLY NOW job by its ID.

---

### 🟡 Local LLM Upgrade (Optional — Batch Automation)

> ⚠️ **STATUS: NOT YET BUILT** — `src/llm_scorer.py` does not exist yet.
> Use the Claude Classifier above instead. This section documents the intended design.

**When to use:** You want automated batch scoring of all 5K candidates overnight without running Claude manually.

**Check if Ollama is running:**
```bash
curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "import sys,json; m=json.load(sys.stdin).get('models',[]); print(f'Models: {[x[\"name\"] for x in m]}')" 2>/dev/null || echo "Ollama not running — start with: ollama serve"
```

**Intended design (once `src/llm_scorer.py` is built):**
- Reads `data/scored/YYYY-MM-DD.json` (rule-based P1/P2/P3)
- Sends top ~5K candidates to local model (DeepSeek/Llama) in batches
- Saves LLM classifications to `data/llm_scored/YYYY-MM-DD.json`
- Dashboard regenerated with LLM reasoning per card

**Switching between backends:** The same prompt template will work for both Claude and Ollama — only the execution context changes (Claude = skill runtime, Ollama = HTTP POST to localhost:11434).

---

## 📄 Resume Tailoring Workflow

When user says "I want to apply to [job]", "tailor my resume for [job]", or "build resume for job #[id]":

**Prerequisites check:**
```bash
[ -f "RESUME.md" ] || { echo "❌ RESUME.md not found. Run: cp RESUME.md.example RESUME.md and fill it in."; exit 1; }
```

**Step 1: Get the job details**
- If they reference a job by ID (`#a3f9c1d2`), look it up using the Job ID lookup snippet above
- If they reference a job from the report, find it in scored data by company/title
- Browse to the job URL and extract the full description:
```bash
$B goto <job_url>
$B text
```

**Step 2: Read the user's resume**
```bash
cat RESUME.md   # Clean Markdown — the source of truth for resume tailoring
```

**Step 3: Tailor the resume (Claude's job)**
- Reorder bullet points to lead with most relevant experience for this specific role
- Emphasize matching skills and keywords from the job description
- Adjust or write a summary/objective tailored to this company and role
- **DO NOT fabricate experience** — only reorganize and emphasize existing content
- Note any skill gaps that should be addressed in the cover letter

**Step 4: Generate a beautiful HTML resume**
Output format: clean, single-page HTML with professional CSS. Layout:
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>[Name] — [Role] at [Company]</title>
  <style>
    /* Professional resume CSS */
    body { font-family: system-ui, Georgia, serif; max-width: 800px; margin: 40px auto; color: #1a1a1a; }
    h1 { font-size: 2em; margin-bottom: 4px; }
    .contact { color: #555; margin-bottom: 20px; }
    h2 { border-bottom: 2px solid #1a1a1a; padding-bottom: 4px; margin-top: 24px; }
    .job { margin-bottom: 16px; }
    .job-title { font-weight: bold; }
    .date { float: right; color: #666; }
    ul { margin: 4px 0; padding-left: 20px; }
    li { margin-bottom: 3px; }
    .skills-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    @media print {
      body { margin: 0; font-size: 10pt; }
      .no-print { display: none; }
    }
  </style>
</head>
<body>
  <!-- Header: Name, contact, links -->
  <!-- Summary: 2-3 sentences tailored to this role and company -->
  <!-- Experience: bullets reordered for relevance to this role -->
  <!-- Skills: grouped, most relevant to this role first -->
  <!-- Education -->
  <p class="no-print" style="background:#e8f4fd;padding:12px;border-radius:6px;margin-top:32px;">
    💡 To save as PDF: Press <strong>Cmd+P</strong> → Save as PDF
  </p>
</body>
</html>
```

**Step 5: Save the tailored resume**
```bash
mkdir -p resumes
# Format: resumes/YYYY-MM-DD-company-role.html
# Example: resumes/2026-03-15-netflix-analytics-engineer.html
```

**Step 6: Present to user**
- State the filename: "Saved to `resumes/2026-03-15-netflix-analytics-engineer.html`"
- Tell them: "Open in your browser and press **Cmd+P → Save as PDF** to get your PDF"
- Show what changed: which bullets were elevated, which keywords were emphasized
- Note any skill gaps to address in a cover letter
- Ask: "Want me to write the cover letter too?"

---

## 🔍 LinkedIn Integration (via G-Stack Browse)

### ⚠️ Prerequisites
```bash
# Step 1: Verify G-Stack browse is available
B=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null | head -1)
if [ -z "$B" ]; then
  echo "ERROR: G-Stack browse not found. LinkedIn integration unavailable."
  echo "Install G-Stack first, then re-run this section."
  exit 1
fi
echo "✅ G-Stack found: $B"
```

If the guard fails, tell the user: **"LinkedIn scraping requires G-Stack browse. This section is not available without it."**

### Netflix Verification Test Case
Netflix is in our JBA pipeline (Workday) AND on LinkedIn — use it as ground-truth to verify scraping works:
```bash
# How many Netflix jobs already in our pipeline?
python3 -c "
import json
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
netflix = [j for j in jobs if 'netflix' in j.get('company','').lower()]
print(f'Netflix jobs in JBA pipeline: {len(netflix)}')
for j in netflix[:5]:
    print(f'  {j[\"title\"]} — {j.get(\"location\",\"\")} — score: {j[\"_score\"]:.1f}')
"
# Then scrape Netflix on LinkedIn and compare. If LinkedIn finds MORE → great signal.
```

### Setup: Import Brave Cookies
```bash
# Quit Brave completely first, then:
$B cookie-import-browser brave

# Verify login — should show the feed, not a login page
$B goto https://www.linkedin.com/feed
$B snapshot
```

### Search LinkedIn Jobs
```bash
# Adjust keywords and location to match your profile
$B goto "https://www.linkedin.com/jobs/search/?keywords=business+intelligence+analyst&location=United+States&f_WT=2"
$B snapshot

# Extract job card list
$B text ".jobs-search__results-list"

# Click a specific job: check your snapshot output for the element ref (e.g. @e5, @e12)
# IMPORTANT: @eN references are dynamic — always use the actual number from YOUR snapshot
# $B click @e5   ← example; your number will differ
$B text ".jobs-description"
```

### Cross-Reference Connections
```bash
# View connections at a target company
$B goto "https://www.linkedin.com/company/anthropic/people/"
$B text
# Look for 1st / 2nd degree connection indicators
```

---

## How to Present Results
1. Read the terminal summary from Step 3 (report)
2. Present the P1 count prominently: "Found X P1 jobs — apply today!"
3. Show top 5-10 P1 matches with title, company, location, score, and job ID
4. Mention P2 count: "Plus Y strong P2 matches worth applying this week"
5. Note any scrape failures from Step 1 output
6. Tell user: "Full report saved to `data/reports/YYYY-MM-DD.csv`"
7. Tell user: "Dashboard at `site/index.html` — open in your browser!"
8. Offer: "Want me to classify these and build a tailored resume for the best match?"

## Profile Updates
User wants to change preferences → use Conversational Profile Setup above

## Quick Re-run (cached data)
If user wants a quick re-score without re-downloading:
```bash
python -m src.scraper --skip-download --skip-live
python -m src.matcher
python -m src.report
python -m src.site_generator
```

## Troubleshooting
- **RESUME.md missing** → `cp RESUME.md.example RESUME.md` then fill in your info
- **profile.yaml missing** → `cp config/profile.yaml.example config/profile.yaml` then fill in your info
- **No jobs found** → Check `data/jobs/` has today's file; re-run `python -m src.scraper`
- **Low P1 count** → Broaden `target_roles` in `config/profile.yaml`
- **Scrape failures** → Check internet connection; specific ATS may be down temporarily
- **LinkedIn blocked** → Re-import cookies: `$B cookie-import-browser brave` (Brave must be closed)
- **LLM scorer crash** → `src/llm_scorer.py` not built yet — use Claude Classifier above instead
