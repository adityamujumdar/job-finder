---
name: classify-jobs
version: 1.0.0
description: |
  Classify scored job matches into APPLY NOW / APPLY THIS WEEK / STRETCH / SKIP
  using Claude as the LLM. Reads today's scored data and your profile, then ranks
  each candidate job against your background and gives a clear action for each.
---

# JobHunter AI — Classify Jobs

## Trigger
"classify jobs", "classify my P1 jobs", "rank these jobs", "which jobs should I apply to",
"which of these should I apply to first", "/classify-jobs"

## First-Time Setup Check
```bash
[ -f "config/profile.yaml" ] || echo "❌ Missing profile — run: cp config/profile.yaml.example config/profile.yaml"
python3 -c "import json; jobs=json.load(open('data/scored/$(date +%Y-%m-%d).json')); print(f'✅ {len(jobs)} jobs loaded')" 2>/dev/null \
  || echo "❌ No scored data — run /jobhunter first to generate today's jobs"
```

---

## Step 1 — Load Candidates

```bash
python3 -c "
import json
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
p1 = [j for j in jobs if j.get('_priority') == 'P1']
candidates = p1 if p1 else [j for j in jobs if j.get('_priority') == 'P2']
tier = 'P1' if p1 else 'P2 (no P1 today)'
print(f'Classifying {len(candidates)} {tier} jobs')
print(json.dumps(candidates[:25], indent=2))
"
```

## Step 2 — Read Profile

```bash
cat config/profile.yaml
# Note: target_roles, skills, target_level, years_experience, location
```

## Step 3 — Classify Each Job

For each candidate, read the title, company, and description, then assign:

| Bucket | Criteria |
|--------|----------|
| **🎯 APPLY NOW** | Title ✅ + core skills ✅ + level ✅ + real tech company ✅ |
| **📅 APPLY THIS WEEK** | Good match, one minor gap (missing 1 skill, slight level mismatch) |
| **⚡ STRETCH** | Interesting but meaningfully underqualified — apply if excited |
| **⏭️ SKIP** | False positive: wrong function, staffing firm, or wrong seniority |

**SKIP signals:** "data center" in description, SWE/DevOps role mislabeled as data, staffing/consulting agency, requires 10+ years when you have fewer.

## Step 4 — Output

```
🎯 APPLY NOW (today):
  #a3f9c1d2 — Netflix Analytics Engineer (97.9) — SQL + Tableau, exact level match
  #b2c1d3e4 — Anthropic Data Analyst (92.8) — Python + BI stack, mission-driven

📅 APPLY THIS WEEK:
  #c4d5e6f7 — Stripe BI Analyst (85.2) — Strong fit, missing dbt (learnable)

⚡ STRETCH:
  #d6e7f8a9 — OpenAI Research Analyst (78.1) — Heavy ML context, worth trying

⏭️ SKIP:
  #e8f9a0b1 — Acme Corp Data Infrastructure (false positive — SWE infra role)
```

Note: Job IDs are 8-char hex (0-9, a-f). Copy any ID to use with `/tailor-resume`.

## After Classification

Offer to build a tailored resume for any APPLY NOW job:
> "Want me to build a resume for job #a3f9c1d2?"
→ Use `/tailor-resume` with that ID.

## Looking Up a Job by ID

```bash
python3 -c "
import json, hashlib
jobs = json.load(open('data/scored/$(date +%Y-%m-%d).json'))
jid = 'a3f9c1d2'  # replace with actual ID
match = next((j for j in jobs if hashlib.sha256(j.get('url','').encode()).hexdigest()[:8] == jid), None)
if match:
    print(f\"{match['title']} @ {match['company']}\")
    print(f\"URL: {match.get('url','')}\")
else:
    print('Job not found — may be from a different date')
"
```
