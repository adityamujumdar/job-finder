# Engineering Review — JobHunter AI v2 (March 15, 2026)

## What Changed Since Last Review

| Fix | Before | After |
|-----|--------|-------|
| Title scoring | Token bags: "Data Center Controls Eng" = 0.95 | Phrase matching: 0.15 ✅ |
| Jobs count | 2,297 (live-only run) | 502,747 (full JBA) ✅ |
| Scored output | 162MB (all 477K) | 2.7MB (P1-P3 only, 8,215 jobs) ✅ |
| Company blocklist | None (staffing farms in results) | 8 blocked (jobgether, launch2, etc.) ✅ |
| Dashboard companies | 9 (broken data) | 2,320 with searchable dropdown ✅ |
| Netflix config | Lever (wrong, 0 jobs) | Workday (correct) ✅ |
| False positives in P1 | ~50% | 0% ✅ |

**All 79 tests pass in 0.66s.**

---

## Architecture: Adding Three New Capabilities

### 1. Local LLM Scorer (DeepSeek, 12GB GPU)

**Purpose:** Classify borderline jobs that rule-based scoring can't distinguish.

**Architecture:**
```
Rule-based pre-filter (502K → ~5K, 11s)
  │
  ▼
Local DeepSeek HTTP API (5K candidates, ~10-30 min on 12GB GPU)
  │
  ├── Input: job title, company, location, level + user profile
  ├── Prompt: "Rate 0-100 how relevant this job is for [profile]. Return JSON."
  ├── Batch: 5-10 jobs per prompt for efficiency
  ├── Output: {relevance: 87, reasoning: "Strong BI match...", skills: ["SQL","Tableau"]}
  │
  ▼
Merged scoring: final_score = 0.4 * rule_score + 0.6 * llm_score
```

**Implementation: `src/llm_scorer.py`**
```python
import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"  # or llama.cpp endpoint
MODEL = "deepseek-r1:8b"  # or whatever's loaded

def score_batch(jobs: list[dict], profile: dict) -> list[dict]:
    """Score a batch of jobs using local LLM."""
    prompt = build_prompt(jobs, profile)
    response = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2000}
    }, timeout=120)
    return parse_llm_response(response.json()["response"], jobs)

def build_prompt(jobs, profile):
    roles = ", ".join(profile.get("target_roles", []))
    skills = ", ".join(profile.get("skills", []))
    location = profile.get("location", "")
    
    job_list = "\n".join(
        f"{i+1}. {j['title']} | {j['company']} | {j.get('location','')} | {j.get('skill_level','')}"
        for i, j in enumerate(jobs)
    )
    
    return f"""You are a job matching assistant. Rate each job's relevance (0-100) for this candidate:

Profile: {roles} with skills in {skills}, based in {location}, open to remote.

Jobs:
{job_list}

For each job, return a JSON array:
[{{"job": 1, "score": 85, "reason": "Strong BI match", "skills": ["SQL","Tableau"]}}]

Only rate based on title/company/location fit. Be strict: a "Software Engineer" is NOT a BI role."""
```

**Performance on 12GB GPU:**
- DeepSeek 7B/8B: ~15-30 tokens/sec → 5K jobs in batches of 10 = 500 prompts → ~20-40 min
- DeepSeek 1.5B (faster): ~50-80 tokens/sec → ~10-15 min
- Can run overnight or during pipeline if needed

**Fallback:** If GPU is busy or slow, skip LLM scoring — rule-based results are still good (zero false positives).

### 2. LinkedIn Scraping via G-Stack Browse

**Purpose:** Find jobs not in ATS platforms (Google, Apple, Amazon, Meta, Microsoft, startups with own career sites).

**Architecture:**
```
Claude SKILL.md triggers LinkedIn scraping
  │
  ├── Import Brave cookies: $B cookie-import-browser brave
  ├── Verify auth: $B goto linkedin.com/feed → check logged in
  │
  ▼
Search LinkedIn jobs (by keywords from profile)
  ├── $B goto "https://linkedin.com/jobs/search/?keywords=business+intelligence&f_WT=2"
  ├── $B snapshot → extract job cards
  ├── Paginate: scroll or click "next"
  ├── Extract per job: title, company, location, url, posted_date
  │
  ▼
Merge into pipeline
  ├── Add ats: "linkedin" to each job
  ├── Dedup: company + normalized_title against JBA data
  ├── Score with same matcher
  ├── Save alongside JBA results
```

**Implementation: `src/linkedin_scraper.py`**
- Claude orchestrates via SKILL.md (not automated — needs cookie auth)
- Jobs saved to `data/linkedin/YYYY-MM-DD.json`
- Merged into `data/jobs/` by scraper.py

**Rate limiting:** LinkedIn blocks after ~100 pages. Respect delays (3-5s between pages). Cookie expires after ~30 days — user re-imports from Brave.

### 3. Company Intelligence Router

**Purpose:** When user mentions a company, Claude automatically knows:
- What ATS platform the company uses
- Whether it's in JBA's seed data
- Whether to scrape via ATS, LinkedIn, or direct career site
- The correct slug/URL format

**Implementation: Lookup in SKILL.md + `data/seed/` files**

```
User: "Add Google to my preferred companies"
Claude: 
  1. Check data/seed/greenhouse.json → "google" not found
  2. Check data/seed/workday.json → "google" not found  
  3. Check data/seed/lever.json → "google" not found
  4. Response: "Google uses their own career site, not a standard ATS. 
     I can search LinkedIn for Google jobs instead. Want me to do that?"
  5. If yes → linkedin scrape with "Google" + user's target roles

User: "Add Stripe to my preferred companies"
Claude:
  1. Check data/seed/greenhouse.json → "stripe" found ✅
  2. Add to config/profile.yaml under greenhouse
  3. Response: "Stripe is on Greenhouse. Added to your preferred companies.
     I'll live-scrape their latest jobs on the next pipeline run."
```

**Data structure for routing:**
```python
# Already exists in data/seed/ — Claude reads these:
# data/seed/greenhouse.json — 4,665 company slugs
# data/seed/lever.json — 1,118 company slugs  
# data/seed/workday.json — 3,493 company slugs
# data/seed/ashby.json — 798 company slugs
# data/seed/bamboohr.json — 2,519 company slugs
```

---

## SKILL.md Intelligence Updates

### Company Awareness
When user mentions a company:
1. Search all seed files for the company slug
2. If found → tell user which ATS, add to preferred_companies, offer live scrape
3. If not found → suggest LinkedIn scraping or checking the company's career page directly
4. If company has >1000 jobs in JBA → might be a staffing firm, verify with user

### Job Application Flow
When user wants to apply:
1. Claude opens job URL via G-Stack: `$B goto <url>`
2. Claude extracts full job description: `$B text`
3. Claude analyzes fit: matching skills, missing skills, experience fit
4. Claude tailors resume: reads `aditya_resume.tex`, reorders/emphasizes bullets
5. Claude saves: `resumes/YYYY-MM-DD-company-role.tex`
6. Claude offers to generate cover letter
7. Dashboard tracks: mark as "Applied" (saved in localStorage)

### Local LLM Integration
When running full pipeline:
1. Check if Ollama/llama.cpp is running: `curl http://localhost:11434/api/tags`
2. If available → run LLM scoring on top ~5K candidates after rule-based scoring
3. If not available → skip, use rule-based only (still good)
4. LLM results stored in `data/llm_scored/YYYY-MM-DD.json`
5. Dashboard shows LLM reasoning if available

---

## File Changes Plan

```
NEW FILES:
  src/llm_scorer.py          — Local DeepSeek batch classification
  src/linkedin_scraper.py    — LinkedIn job search via G-Stack browse
  src/resume_engine.py       — LaTeX resume tailoring per job

MODIFIED:
  src/matcher.py             — Integrate LLM scores into final ranking
  src/scraper.py             — Merge LinkedIn jobs into pipeline
  src/site_generator.py      — Show LLM reasoning, skill match in cards
  src/config.py              — LLM endpoint config, LinkedIn settings
  SKILL.md                   — Company routing, LLM trigger, apply workflow
  config/profile.yaml        — LinkedIn search keywords section

UNCHANGED:
  src/downloader.py          — Working fine
  src/jba_fetcher.py         — Working fine
  src/report.py              — Working fine (CSV output)
```

---

## Performance Budget

| Step | Current | After Changes |
|------|---------|---------------|
| JBA Download | 1.3s (cached) | Same |
| Rule-based scoring | 11s (502K jobs) | Same |
| LLM scoring | N/A | ~20-40 min (5K candidates on 12GB GPU) |
| LinkedIn scrape | N/A | ~2-5 min (50-100 pages) |
| Site generation | <1s | Same |
| **Total (without LLM)** | **~15s** | **~3-8 min** (if LinkedIn included) |
| **Total (with LLM)** | N/A | **~25-45 min** (can run overnight) |

The LLM step is optional and can run as a separate pass:
```bash
python -m src.llm_scorer          # Run independently, merges into scored data
python -m src.site_generator      # Regenerate dashboard with LLM insights
```

---

## Test Plan

| Area | Tests to Add |
|------|-------------|
| Phrase matching | ✅ Already passing (79 tests) |
| LLM scorer | Mock HTTP responses, test batch prompt building, test score merging |
| LinkedIn scraper | Integration test with mock HTML, test dedup against JBA |
| Resume engine | Test LaTeX generation, test bullet reordering logic |
| Company routing | Test seed data lookup, test platform detection |
| Dashboard | Manual: verify dropdowns show all 2,320 companies |

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| LinkedIn blocks scraping | Respect rate limits (3-5s delays), cookie refresh every 30 days |
| DeepSeek OOMs on 12GB GPU | Use smaller model (1.5B) or reduce batch size |
| Brave cookies expire | SKILL.md prompts user to re-import |
| GitHub Actions rate limit | Daily run only, cache aggressively |
| JBA changes data format | Vendored fetcher with SHA pinning + update script |
