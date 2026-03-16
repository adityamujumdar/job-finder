# JobHunter AI — Claude Skill

## Trigger
User says any of: "find me jobs", "job search", "find jobs", "run jobhunter", "daily report", "show jobs", "set up my profile", "update profile", "apply to", "tailor resume", "build resume for job", "classify jobs", "rank these jobs", "tell me about job #"

## Setup (first time only)
```bash
cd /Users/adityamujumdar/projects/job-finder
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
2. Analyze fit against the user's profile:
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
# Look up job details by its 8-char ID in today's scored data
python3 -c "
import json, sys
data = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
job_id = sys.argv[1]
import hashlib
for j in data:
    url = j.get('url', '')
    if hashlib.sha256(url.encode()).hexdigest()[:8] == job_id:
        print(json.dumps(j, indent=2))
        break
" a3f9c1d2
```

**When the user says:** "build resume for job a3f9c1d2" or "tell me about #a3f9c1d2":
1. Look up the job using the snippet above
2. Browse to its URL for the full description
3. Proceed to Resume Tailoring or Job Analysis below

---

## 🧠 Candidate Classification Per Position

When the user says "classify jobs for [role]" or "which of these jobs should I apply to first?" or "rank these P1 jobs":

1. **Load the scored jobs:**
```bash
python3 -c "
import json
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
p1 = [j for j in jobs if j.get('_priority') == 'P1']
print(json.dumps(p1[:20], indent=2))
"
```

2. **For each candidate job, Claude should classify:**
   - **APPLY NOW** — Strong match on title + skills + level + company type
   - **APPLY THIS WEEK** — Good match, minor gaps (missing one skill, slight seniority mismatch)
   - **SKIP** — Wrong function (e.g., BI title but actually a software engineering role)
   - **STRETCH** — Interesting but you're underqualified; apply anyway if interested

3. **Classification criteria against Aditya's profile:**
   - Core match: title contains BI/analytics/data analyst keywords ✅
   - Skills match: SQL, Python, Tableau/Looker/Power BI mentioned ✅
   - Level match: 3-7 years experience, senior/mid-level (not director/VP) ✅
   - Company type: tech company, not staffing/consulting ✅
   - Wrong: "data center", "data infrastructure SWE", "marketing analyst" with no BI tools

4. **Output format:**
```
🎯 APPLY NOW (today):
  #a3f9c1d2 — Netflix Analytics Engineer (score: 97.9) — SQL + Tableau, perfect level
  #b2c1d3e4 — Anthropic Data Analyst (score: 92.8) — Python + BI stack, mission-driven

📅 APPLY THIS WEEK:
  #c4d5e6f7 — Stripe BI Analyst (score: 85.2) — Good fit, missing dbt experience

⚡ STRETCH (apply if excited):
  #d6e7f8g9 — OpenAI Research Analyst (score: 78.1) — Heavy ML context, worth trying

⏭️ SKIP:
  #e8f9g0h1 — Acme Data Infrastructure Engineer (false positive, SWE role)
```

5. **After classification:** Offer to build resume for any APPLY NOW job by its ID.

---

## 📄 Resume Tailoring Workflow

When user says "I want to apply to [job]", "tailor my resume for [job]", or "build resume for job #[id]":

1. **Get the job details:**
   - If they reference a job by ID (`#a3f9c1d2`), look it up using the Job ID lookup snippet above
   - If they reference a job from the report, find it in scored data by company/title
   - Use G-Stack browse to visit the job URL and extract the full description:
   ```bash
   $B goto <job_url>
   $B text
   ```

2. **Read the user's current resume (as plain text reference):**
   ```bash
   cat aditya_resume.tex
   # Extract the key sections: experience bullets, skills, education
   ```

3. **Tailor the resume:**
   - Reorder bullet points to lead with most relevant experience for this specific role
   - Emphasize matching skills and keywords from the job description
   - Adjust summary/headline if present
   - DO NOT fabricate experience — only reorganize and emphasize existing content
   - Note any skill gaps to mention in the cover letter

4. **Generate a beautiful HTML resume:**
   - Output format: clean, single-page HTML with professional CSS
   - Font: system-ui or Georgia for body, monospace for technical skills
   - Layout: single column with clear sections (Summary, Experience, Skills, Education)
   - Color: white background, dark text, subtle accent color (navy or slate)
   - Print-ready: CSS `@media print` ensures clean PDF when user does Cmd+P
   - Template structure:
   ```html
   <!DOCTYPE html>
   <html>
   <head>
   <meta charset="UTF-8">
   <title>Aditya Mujumdar — [Role] at [Company]</title>
   <style>
     /* ... professional resume CSS ... */
     @media print {
       body { margin: 0; }
       .no-print { display: none; }
     }
   </style>
   </head>
   <body>
     <!-- Header: Name, contact, links -->
     <!-- Summary: 2-3 sentences tailored to this role -->
     <!-- Experience: bullets reordered for this role -->
     <!-- Skills: grouped, most relevant first -->
     <!-- Education -->
   </body>
   </html>
   ```

5. **Save the tailored version:**
   ```bash
   mkdir -p resumes
   # Format: resumes/YYYY-MM-DD-company-role.html
   # Example: resumes/2026-03-15-netflix-analytics-engineer.html
   ```

6. **Present to user:**
   - State the filename: "Saved to resumes/2026-03-15-netflix-analytics-engineer.html"
   - Tell them: "Open in browser and Cmd+P → Save as PDF to get your PDF"
   - Show what was changed: which bullets were elevated, which skills were highlighted
   - Note any skill gaps they should address in a cover letter
   - Ask if they want a cover letter too (Claude can write it directly in the response)

---

## 🔍 LinkedIn Integration (via G-Stack Browse)

### Netflix Verification Test Case
Netflix is in our JBA pipeline (Workday slug: `netflix|wd1|netflix`) AND on LinkedIn.
Use Netflix as the ground-truth test to verify LinkedIn scraping is working:
1. Scrape Netflix jobs from LinkedIn (see below)
2. Compare against jobs already in our pipeline: `grep -i netflix data/scored/$(date +%Y-%m-%d).json | head -5`
3. If LinkedIn finds jobs not in JBA → LinkedIn integration is adding value ✅
4. If LinkedIn finds the same jobs → JBA coverage is already good ✅ (no new data, but connection cross-ref still works)

### Setup: Import Brave Cookies
```bash
BROWSE_OUTPUT=$(browse/bin/find-browse 2>/dev/null || ~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)

# Import cookies from Brave browser (user must quit Brave first on macOS)
$B cookie-import-browser brave

# Verify LinkedIn login
$B goto https://www.linkedin.com/feed
$B snapshot
# Should show the feed, not login page
```

### Search LinkedIn Jobs
```bash
# Build search URL from profile
# Keywords from target_roles, location from profile, f_WT=2 for remote
$B goto "https://www.linkedin.com/jobs/search/?keywords=business+intelligence+analyst&location=United+States&f_WT=2"
$B snapshot

# Extract job cards
$B text ".jobs-search__results-list"

# Get individual job details
$B click @eN  # click on a job card
$B text ".jobs-description"
```

### Cross-Reference Connections
```bash
# On a company page
$B goto "https://www.linkedin.com/company/anthropic/people/"
$B text
# Extract connection names for "You know X at this company" badges
```

---

## 🤖 Local LLM Scoring (DeepSeek on GPU)

When the user wants higher-quality scoring (or says "use LLM", "deep score", "classify jobs"):

### Check if LLM is available
```bash
curl -s http://localhost:11434/api/tags 2>/dev/null | head -5
# If Ollama is running, this returns available models
# If not running, tell user: "Start Ollama with: ollama serve"
```

### Run LLM classification
```bash
python -m src.llm_scorer
# Reads data/scored/YYYY-MM-DD.json (rule-based results)
# Sends top ~5K candidates to local DeepSeek in batches
# Saves to data/llm_scored/YYYY-MM-DD.json
# Merges LLM scores with rule-based scores
# ~20-40 min on 12GB GPU
```

### After LLM scoring
```bash
python -m src.site_generator  # Regenerate dashboard with LLM insights
```

The dashboard will show LLM reasoning per job if available (e.g., "Strong BI match — SQL and Tableau mentioned").

**Note:** LLM scoring is OPTIONAL. Rule-based scoring already has zero false positives in P1. LLM improves borderline P2/P3 classification.

---

## How to Present Results
1. Read the terminal summary from Step 3
2. Present the P1 count prominently: "Found X P1 jobs — apply today!"
3. Show top 5-10 P1 matches with title, company, location, score
4. Mention P2 count: "Plus Y strong P2 matches worth applying this week"
5. Note any scrape failures from Step 1 output
6. Tell user: "Full report saved to data/reports/YYYY-MM-DD.csv"
7. Tell user: "Dashboard at site/index.html — open in your browser!"
8. Offer: "Want me to tailor your resume for any of these?"

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
- No jobs found → Check data/jobs/ has today's file
- Low P1 count → Suggest broadening target_roles in profile.yaml  
- Scrape failures → Check internet connection, specific ATS may be down
- LinkedIn blocked → Re-import cookies: `$B cookie-import-browser brave`
- Resume tailoring → Needs aditya_resume.tex in project root
