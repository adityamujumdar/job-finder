---
name: tailor-resume
version: 1.0.0
description: |
  Build a beautiful, tailored HTML resume for a specific job. Reads RESUME.md
  (your base resume), fetches the job description, reorders and emphasizes the
  most relevant experience, and outputs a print-ready HTML file (Cmd+P → PDF).
---

# JobHunter AI — Tailor Resume

## Trigger
"tailor my resume", "build resume for", "I want to apply to", "build resume for job #",
"make a resume for", "resume for [company]", "/tailor-resume"

## Prerequisite Check
```bash
[ -f "RESUME.md" ] && echo "✅ RESUME.md found" \
  || echo "❌ Missing — run: cp RESUME.md.example RESUME.md  (then fill in your info)"
```
If RESUME.md is missing, stop and tell the user to create it before continuing.

---

## Step 1 — Identify the Job

**By job ID** (from dashboard card or `/classify-jobs` output):
```bash
python3 -c "
import json, hashlib
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
jid = 'REPLACE_WITH_ID'   # e.g. a3f9c1d2
match = next((j for j in jobs if hashlib.sha256(j.get('url','').encode()).hexdigest()[:8] == jid), None)
if match:
    print(f\"Title: {match['title']}\")
    print(f\"Company: {match['company']}\")
    print(f\"URL: {match.get('url','')}\")
"
```

**By company/title** (search scored data):
```bash
python3 -c "
import json
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
hits = [j for j in jobs if 'netflix' in j.get('company','').lower()]  # adjust filter
for j in hits[:5]:
    import hashlib
    jid = hashlib.sha256(j.get('url','').encode()).hexdigest()[:8]
    print(f'#{jid} — {j[\"title\"]} @ {j[\"company\"]} ({j[\"_score\"]:.1f})')
"
```

## Step 2 — Get the Full Job Description

Browse to the job URL and extract the description:
```bash
$B goto <job_url>
$B text
```
If G-Stack is unavailable, ask the user to paste the job description directly.

## Step 3 — Read Your Resume

```bash
cat RESUME.md
```

## Step 4 — Tailor (Claude's job)

Analyze the job description against RESUME.md, then:
- **Reorder** experience bullets — most relevant to THIS role goes first
- **Emphasize** skills and tools mentioned in the job description
- **Write a tailored summary** (2-3 sentences for this company/role)
- **Group skills** — put the job's required tools first in the skills section
- **DO NOT fabricate** experience — only reorganize and emphasize what exists
- **Note gaps** — list any required skills you don't have (mention in cover letter)

## Step 5 — Generate HTML Resume

Output a complete, single-page HTML file:

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

  <!-- SUMMARY — tailored to THIS role -->
  <h2>Summary</h2>
  <p>[2-3 sentences: who you are, what you bring, why this company/role specifically]</p>

  <!-- EXPERIENCE — reordered for relevance -->
  <h2>Experience</h2>
  <!-- Most relevant role first -->

  <!-- SKILLS — job-required tools first -->
  <h2>Skills</h2>
  <div class="skills-row">
    <!-- Group by category -->
  </div>

  <!-- EDUCATION -->
  <h2>Education</h2>

  <p class="hint" style="margin-top:28px;padding:10px;background:#f0f7ff;border-radius:5px;font-size:9pt;color:#555;">
    💡 Press <strong>Cmd+P</strong> → <em>Save as PDF</em> to export your resume.
  </p>
</body>
</html>
```

## Step 6 — Save

```bash
mkdir -p resumes
# resumes/YYYY-MM-DD-company-role.html
# e.g.: resumes/2026-03-16-netflix-analytics-engineer.html
```

## Step 7 — Present to User

- "Saved to `resumes/2026-03-16-netflix-analytics-engineer.html`"
- "Open in your browser and press **Cmd+P → Save as PDF**"
- Summarize what changed: which bullets moved up, which keywords emphasized
- List any skill gaps to address in a cover letter
- Ask: "Want me to write the cover letter too?"
