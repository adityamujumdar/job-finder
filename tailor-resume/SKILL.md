---
name: tailor-resume
version: 2.0.0
description: |
  Build a beautiful, tailored HTML resume for a specific job. Reads RESUME.md
  (your base resume), fetches the job description, reorders and emphasizes the
  most relevant experience, and outputs a print-ready HTML file (Cmd+P → PDF).
---

# JobHunter AI — Tailor Resume

## Philosophy

Tailoring a resume is not decoration — it is strategic re-ordering and emphasis of real
facts to serve a specific reader (a hiring manager with 30 seconds). Every word on the
tailored resume must come from RESUME.md or the job description — never fabricated.

Two-pass approach (borrowed from [gstack/review](https://github.com/garrytan/gstack)):
read everything first, analyze second, write last. Never write a line of the resume
before you've read both RESUME.md and the full job description. Skimming leads to
generic resumes that look like every other application.

Evidence before output: show your analysis (what matched, what gaps exist, what you
emphasized) before presenting the HTML. The user should understand *why* each decision
was made, not just receive a document.

Frame skill gaps as investment advice, not failure (borrowed from
[gstack/retro](https://github.com/garrytan/gstack)): "You don't have dbt — worth noting
in a cover letter that you've worked with similar orchestration tools" is better than
"missing: dbt".

---

## NEVER:
- Fabricate experience, skills, or companies — RESUME.md is the only source of truth
- Write the resume before reading RESUME.md and the full job description
- Save a resume file without telling the user exactly where it was saved
- Present the HTML without first showing your analysis (what you changed and why)
- Add skills to the skills section that aren't in RESUME.md
- Invent a summary — base it on actual experience from RESUME.md, angled toward this role
- Stop and tell the user to "follow setup steps" or "run X first" — fix it for them

---

## Trigger
"tailor my resume", "build resume for", "I want to apply to", "build resume for job #",
"make a resume for", "resume for [company]", "/tailor-resume"

---

## Step 0 — Prerequisite Check & Auto-Fix

Run this check first, every time. **Fix everything automatically.**

```bash
# 1. Ensure .venv exists
if [ ! -d ".venv" ]; then
  echo "⚙️  Creating .venv..."
  python3 -m venv .venv && source .venv/bin/activate && pip install -q -r requirements.txt
  echo "✅ Environment ready"
else
  source .venv/bin/activate
fi

# 2. Check for RESUME.md
[ -f "RESUME.md" ] && echo "✅ RESUME.md found" || echo "⚙️  No RESUME.md yet — will ask user for their resume"

# 3. Check scored data (needed for job ID lookup)
python3 -c "
import pathlib
today = __import__('datetime').date.today().isoformat()
path = pathlib.Path(f'data/scored/{today}.json')
print('✅ Scored data found' if path.exists() else '⚙️  No scored data — will run pipeline if job ID lookup is needed')
" 2>/dev/null
```

**If RESUME.md is missing:** Ask the user to provide their resume. Use AskUserQuestion with these options:

1. **"Point me to your resume file"** — User gives a path (e.g. `~/Documents/resume.pdf`, `~/Desktop/Resume.docx`). Read the file, extract the content, and write it to `RESUME.md` in markdown format.
2. **"I'll paste it here"** — User pastes their resume text. Parse it and write to `RESUME.md`.
3. **"I have it on LinkedIn"** — Browse their LinkedIn profile to extract experience, then write `RESUME.md`.

After the user provides their resume (by any method), convert it to clean markdown and save as `RESUME.md`:
```bash
# Confirm with user before writing
echo "Writing your resume to RESUME.md..."
```
Then tell them: "✅ Created RESUME.md from your resume. This stays local and is never uploaded anywhere." Then continue with the tailoring.

**If scored data is missing and user provides a job ID:** Run the pipeline automatically:
```bash
python -m src.scraper --skip-live && python -m src.matcher
```
Then look up the job ID and continue.

**If scored data is missing and user provides a job URL or description:** No pipeline needed — proceed directly with the provided information.

---

## Step 1 — Identify the Job

**By job ID** (from dashboard or `/classify-jobs`):

```bash
python3 -c "
import json, hashlib, pathlib
today = __import__('datetime').date.today().isoformat()
jobs = json.loads(pathlib.Path(f'data/scored/{today}.json').read_text())
jid = 'REPLACE_WITH_ID'   # e.g. a3f9c1d2
match = next((j for j in jobs if hashlib.sha256(j.get('url','').encode()).hexdigest()[:8] == jid), None)
if match:
    print(f\"Title: {match['title']}\")
    print(f\"Company: {match['company']}\")
    print(f\"URL: {match.get('url','')}\")
    print(f\"Score: {match.get('_score', 0):.1f}\")
else:
    print('Job not found — check the ID or try a different date')
    print('Available: ls data/scored/')
"
```

**By company/title search**:

```bash
python3 -c "
import json, hashlib, pathlib
today = __import__('datetime').date.today().isoformat()
jobs = json.loads(pathlib.Path(f'data/scored/{today}.json').read_text())
query = 'netflix'   # adjust
hits = [j for j in jobs if query in j.get('company','').lower() or query in j.get('title','').lower()]
for j in hits[:5]:
    jid = hashlib.sha256(j.get('url','').encode()).hexdigest()[:8]
    print(f'#{jid} — {j[\"title\"]} @ {j[\"company\"]} ({j.get(\"_score\",0):.1f})')
"
```

---

## Step 2 — Get the Full Job Description

**Using G-Stack browser (preferred):**

```bash
# Setup browse (run once per session)
BROWSE_OUTPUT=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)
if [ -z "$B" ]; then echo "BROWSE_NOT_AVAILABLE"; fi

# Fetch the job description
$B goto <job_url>
$B text
```

This works for ANY job URL — including companies not in JBA (Scotiabank, government sites,
LinkedIn listings, etc.). The job does not need to be in the scored dataset.

**For Greenhouse API jobs** (Stripe, Anthropic, etc.), you can also fetch structured data:
```bash
python3 -c "
import urllib.request, json, re, html
url = 'https://boards-api.greenhouse.io/v1/boards/<company>/jobs/<job_id>'
data = json.loads(urllib.request.urlopen(url, timeout=15).read())
text = html.unescape(data.get('content',''))
text = re.sub(r'<[^>]+>', '\n', text)
print(re.sub(r'\n{3,}', '\n\n', text).strip())
"
```

**If G-Stack is unavailable:** Ask the user to paste the job description directly.

**Read the ENTIRE description.** Do not skim. Every bullet point and requirement section
matters — the keywords in "Nice to Have" are real signals even if not required.

---

## Step 3 — Read Your Resume

```bash
cat RESUME.md
```

Read every line. Note:
- All companies, roles, and dates
- Every skill and tool named
- Every metric or impact bullet
- What's strongest vs what's thinner

**Do not start the analysis until you've read both RESUME.md and the full job description.**

---

## Step 4 — Two-Pass Analysis

### Pass 1: Match Assessment (what to emphasize)

Answer these before writing anything:

```
Job requires:    [list required skills from JD]
You have:        [exact matches from RESUME.md]
You're missing:  [gaps — be honest]
Best bullets:    [3-5 bullets from RESUME.md that are most relevant to THIS role]
Best role:       [which past role is most relevant? it goes first in Experience]
Summary angle:   [one sentence that connects your background to this company's mission]
```

Show this analysis to the user before generating HTML. They should see your reasoning.

### Pass 2: Resume Generation (what to write)

With the match assessment complete, build the HTML:

- **Summary** — 2-3 sentences: who you are + what you bring + why this company/role specifically
  Anchor in actual experience, not generic claims. "Led 3 data pipeline rebuilds" > "passionate data professional"
- **Experience** — most relevant past role first (reorder if needed)
  Pull forward the bullets that directly answer the job's requirements
  Bullets that don't resonate for this role can move down or be trimmed
- **Skills** — job-required tools first, grouped by category
  Only list skills from RESUME.md. If the job requires something you don't have, note it below.
- **Gaps** — list honestly. Will go into the cover letter offer at the end.

---

## Step 5 — Generate HTML Resume

Output a complete, single-page, print-ready HTML file:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>[Your Name] — [Role] at [Company]</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, Georgia, serif;
      font-size: 10.5pt;
      color: #1a1a1a;
      max-width: 780px;
      margin: 32px auto;
      padding: 0 24px;
      line-height: 1.45;
    }
    h1 { font-size: 22pt; letter-spacing: -0.5px; margin-bottom: 2px; }
    .contact { color: #555; font-size: 9.5pt; margin-bottom: 18px; }
    .contact a { color: #1a6fa8; text-decoration: none; }
    h2 {
      font-size: 11pt;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      border-bottom: 1.5px solid #1a1a1a;
      padding-bottom: 2px;
      margin: 18px 0 8px;
    }
    .job-header { display: flex; justify-content: space-between; align-items: baseline; }
    .job-title { font-weight: 700; font-size: 10.5pt; }
    .job-company { font-style: italic; }
    .date { font-size: 9.5pt; color: #555; }
    ul { margin: 4px 0 0 16px; }
    li { margin-bottom: 2px; }
    .skills-row { display: flex; gap: 24px; flex-wrap: wrap; }
    .skills-group { flex: 1; min-width: 160px; }
    .skills-label { font-weight: 700; font-size: 9.5pt; }
    @media print {
      body { margin: 0; padding: 12px 18px; font-size: 9.5pt; }
      .hint { display: none; }
    }
  </style>
</head>
<body>

  <!-- HEADER -->
  <h1>[Full Name]</h1>
  <p class="contact">
    [City, ST] · <a href="mailto:[email]">[email]</a> · <a href="[linkedin]">LinkedIn</a>
  </p>

  <!-- SUMMARY — tailored to THIS role, anchored in RESUME.md facts -->
  <h2>Summary</h2>
  <p>[2-3 sentences. Real experience + why this company/role specifically. No generic claims.]</p>

  <!-- EXPERIENCE — most relevant role first -->
  <h2>Experience</h2>

  <div class="job-header">
    <span><span class="job-title">[Job Title]</span> — <span class="job-company">[Company]</span></span>
    <span class="date">[Start] – [End]</span>
  </div>
  <ul>
    <!-- Pull forward bullets that answer this job's requirements. Real data only. -->
    <li>[Most relevant bullet from RESUME.md for this role]</li>
    <li>[Second most relevant]</li>
  </ul>

  <!-- SKILLS — job-required tools first, all from RESUME.md -->
  <h2>Skills</h2>
  <div class="skills-row">
    <div class="skills-group">
      <span class="skills-label">Languages: </span>[Python, SQL, ...]
    </div>
    <div class="skills-group">
      <span class="skills-label">Tools: </span>[Tableau, dbt, ...]
    </div>
  </div>

  <!-- EDUCATION -->
  <h2>Education</h2>
  <div class="job-header">
    <span><span class="job-title">[Degree]</span> — <span class="job-company">[School]</span></span>
    <span class="date">[Year]</span>
  </div>

  <p class="hint" style="margin-top:28px;padding:10px;background:#f0f7ff;border-radius:5px;font-size:9pt;color:#555;">
    💡 Press <strong>Cmd+P</strong> (Mac) or <strong>Ctrl+P</strong> (Windows) → <em>Save as PDF</em>
  </p>
</body>
</html>
```

---

## Step 6 — Save and Present

```bash
mkdir -p resumes
# filename: YYYY-MM-DD-company-role.html
# e.g.: resumes/2026-03-16-netflix-analytics-engineer.html
```

Present in this order:

1. **Where it's saved:** `resumes/2026-03-16-netflix-analytics-engineer.html`
2. **How to export:** "Open in browser → Cmd+P → Save as PDF"
3. **What changed** (specific, anchored):
   - "Moved [Company X] bullet up — it mentions Tableau which is their required tool"
   - "Rewrote summary to mention data pipeline scale, which they listed twice in JD"
4. **Skill gaps** (as investment advice, not failure):
   - "dbt isn't in your resume — worth a sentence in your cover letter: 'I've built similar pipelines with [X], picking up dbt is on my roadmap'"
5. **One offer:** "Want a cover letter for this role?" (one offer, not a menu)

---

## Step 7 — Cover Letter (if asked)

If the user says yes to the cover letter offer:

- Opening paragraph: why this company specifically (research the mission, product, or a recent launch)
- Middle: your most relevant experience bridging directly to their needs
- Closing: address the skill gap proactively, show interest in learning curve
- Length: 3 paragraphs max. Hiring managers read fast.

Save to `resumes/2026-03-16-netflix-analytics-engineer-cover.md`
