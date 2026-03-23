---
name: enhance-jobs
version: 1.0.0
description: |
  LLM-enhanced job analysis — use Claude's semantic understanding to re-score
  titles, extract skills from job descriptions, and surface insights that regex
  misses. Works WITHOUT an API key because YOU are Claude. Uses gstack/browse
  to fetch job descriptions when available.
---

# JobHunter AI — Enhance Jobs (LLM-Powered)

## Philosophy

You ARE the LLM. No API key needed — you read the data and apply semantic understanding
directly. This skill upgrades the regex-based pipeline with your judgment:
- Title matching: "Staff Platform Engineer" is NOT the same as "Data Platform Engineer" — regex can't tell, you can.
- Skill extraction: "Experience with cloud-native architectures" means AWS/GCP/Azure — regex only matches exact words.
- Section awareness: "Python" in "About Us" ≠ "Python" in "Requirements" — you understand context.

Run this after `/jobhunter` to refine P1+P2 results. Non-destructive: writes enhanced
data alongside existing scored data, never overwrites.

Borrowed from [gstack](https://github.com/garrytan/gstack): non-interactive by default,
read full context before acting, anchor every output in actual data.

---

## Only stop for:
- No scored data (run `/jobhunter` first)

## Never stop for:
- gstack not installed (skip browse, use existing enriched data)
- Some jobs failing to fetch (enhance what you can, report what you can't)
- Low job count (enhance 5 or 500)

---

## Trigger
"enhance jobs", "rescore jobs", "llm rescore", "improve scoring", "deep analysis",
"analyze my P1 jobs", "re-rank jobs", "/enhance-jobs"

---

## Step 0 — Load Data

```bash
source .venv/bin/activate 2>/dev/null || true

python3 -c "
import json, pathlib
today = __import__('datetime').date.today().isoformat()
scored_path = pathlib.Path(f'data/scored/{today}.json')
enriched_path = pathlib.Path(f'data/enriched/{today}.json')

if not scored_path.exists():
    print('❌ No scored data — run /jobhunter first')
    exit(1)

jobs = json.loads(scored_path.read_text())
p1 = [j for j in jobs if j.get('_priority') == 'P1']
p2 = [j for j in jobs if j.get('_priority') == 'P2']
print(f'📊 {len(p1)} P1 + {len(p2)} P2 jobs to enhance')

enriched = {}
if enriched_path.exists():
    enriched = json.loads(enriched_path.read_text())
    print(f'📝 {len(enriched)} jobs already enriched')

# Output the P1+P2 job list for Claude to read
candidates = p1 + p2[:50]  # cap at ~50 for context window
for j in candidates[:30]:
    url = j.get('url', '')
    has_desc = url in enriched and not enriched[url].get('unenriched')
    desc_flag = '📄' if has_desc else '⚠️'
    print(f'  {desc_flag} {j.get(\"title\",\"?\")} @ {j.get(\"company\",\"?\")} — {j.get(\"_score\",0):.1f} ({j.get(\"_priority\",\"?\")})')
"
```

```bash
# Load profile for matching context
cat config/profile.yaml
```

---

## Step 1 — Title Re-Scoring (Claude as LLM)

Read all P1+P2 job titles and the user's `target_roles` from profile.yaml.

For EACH job, assign a semantic title relevance score (0.0 to 1.0):

**Scoring guide:**
- **1.0**: Exact match or trivially equivalent ("Backend Engineer" ≈ "Software Engineer, Backend")
- **0.85-0.95**: Same role family, different seniority/specialization
- **0.6-0.85**: Related role, significant overlap in day-to-day work
- **0.3-0.6**: Tangentially related, some skill overlap
- **0.0-0.3**: Different job family entirely

**Critical distinctions regex misses:**
- "Data Engineer" (builds pipelines) vs "Data Analyst" (writes SQL + dashboards) → 0.6, not 1.0
- "Software Engineer - Data Platform" vs "Data Engineer" → 0.9 (same actual work)
- "Staff Platform Engineer" vs "Staff Software Engineer" → 0.85 (same family, different focus)
- "Machine Learning Engineer" vs "Software Engineer" → 0.7 (ML is SWE subspecialty)
- "Technical Program Manager" vs "Software Engineer" → 0.2 (different function entirely)

Output your re-scored titles as a JSON block:

```json
{
  "title_rescores": [
    {"url": "https://...", "title": "...", "regex_score": 85.2, "llm_title_score": 0.92, "reason": "exact role family match"},
    {"url": "https://...", "title": "...", "regex_score": 78.1, "llm_title_score": 0.45, "reason": "TPM, not SWE — false positive"}
  ]
}
```

---

## Step 2 — Skill Extraction from Job Descriptions

For each P1+P2 job that has an enriched description (fetched by the enricher), read the
full description text and extract skills with section awareness.

### If descriptions are missing — fetch them with gstack/browse:

```bash
BROWSE_OUTPUT=$(~/.claude/skills/gstack/browse/bin/find-browse 2>/dev/null)
B=$(echo "$BROWSE_OUTPUT" | head -1)
if [ -n "$B" ]; then
  echo "✅ gstack/browse available — can fetch missing job descriptions"
else
  echo "⚠️ gstack not available — will analyze existing enriched data only"
fi
```

For each unenriched P1 job (up to 10):
```bash
$B goto <job_url>
$B text
```

After fetching, read the description and classify skills:

**For each job description:**
1. Identify sections: Requirements, Nice-to-Have, About Us, Responsibilities
2. Map the user's profile skills against each section
3. Output:
   - `required`: skills explicitly listed under requirements/qualifications
   - `nice_to_have`: skills under preferred/bonus sections
   - `implicit`: skills implied but not named (e.g., "cloud-native" implies AWS/GCP)

```json
{
  "skill_extractions": [
    {
      "url": "https://...",
      "required": ["Python", "SQL", "AWS"],
      "nice_to_have": ["Kubernetes", "Go"],
      "implicit": ["Docker (mentioned cloud-native)"],
      "match_pct": 80,
      "missing_critical": ["Go"]
    }
  ]
}
```

---

## Step 3 — Write Enhanced Data

Save your analysis to `data/enriched/DATE-llm.json` as a sidecar:

```bash
python3 -c "
import json, pathlib
from datetime import date

today = date.today().isoformat()
output = pathlib.Path(f'data/enriched/{today}-llm.json')

# Your analysis goes here — paste your JSON blocks
enhanced = {
    'title_rescores': [],      # from Step 1
    'skill_extractions': [],   # from Step 2
    'source': 'claude-code',   # not API — you are the LLM
    'model': 'claude-code-inline',
}

output.write_text(json.dumps(enhanced, indent=2))
print(f'✅ Enhanced data saved to {output}')
print(f'   {len(enhanced[\"title_rescores\"])} title rescores')
print(f'   {len(enhanced[\"skill_extractions\"])} skill extractions')
"
```

---

## Step 4 — Present Insights

Show a summary of what changed:

```
🧠 LLM Enhancement Results:

📊 Title Re-Scores ({n} jobs):
  ↑ Upgraded: {count} jobs scored higher with semantic matching
  ↓ Downgraded: {count} false positives caught
  = Unchanged: {count} regex was already correct

  Biggest upgrades:
    "Software Engineer - Data Platform" @ Stripe: 72.1 → 88.4 (regex missed role family match)
    
  False positives caught:
    "Technical Program Manager" @ Meta: 81.3 → 52.1 (different function, not SWE)

📝 Skill Analysis ({n} jobs):
  Average skill match: {pct}%
  Common gaps: {skill1} (in {n} jobs), {skill2} (in {n} jobs)
  Your strongest signals: {skill1} (required in {n} P1 jobs)
```

---

## Step 5 — Offer Next Steps

```
What's next?
→ /classify-jobs — classify enhanced results into APPLY NOW / SKIP
→ /tailor-resume — build a resume for your top match
→ /jobhunter — re-run the full pipeline
```

---

## Two Paths — Same Intelligence

This skill works in **two modes** depending on context:

### Mode 1: Claude Code (interactive — you ARE here)
- YOU read the data and apply semantic understanding
- No API key needed — you are the model
- gstack/browse fetches job descriptions you analyze directly
- Results written to `data/enriched/DATE-llm.json`

### Mode 2: Automated (CI/scheduled — API key)
- `src/llm.py` makes Claude API calls (Haiku for cost)
- Set `ANTHROPIC_API_KEY` in environment or `.env`
- Same analysis, same data format, runs without human interaction
- ~$1/day for full pipeline enhancement

**Both modes produce the same data format.** The pipeline doesn't care whether
Claude analyzed the data interactively or via API — it reads the same JSON.
