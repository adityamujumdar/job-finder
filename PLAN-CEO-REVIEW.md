# CEO Review — JobHunter AI v2 (March 15, 2026)

## Current State

**Working:** A pipeline that downloads 502K jobs from 12K+ companies, scores them with phrase-level matching (zero false positives in P1), and publishes a static HTML dashboard with full-featured filtering (company, location, platform dropdowns with 2,320 companies).

**Deployed on:** GitHub Pages at `adityamujumdar.github.io/job-finder`, daily via GitHub Actions, $0/month.

**Results:** 51 P1 jobs (apply now), 1,188 P2 (this week), 6,976 P3 (if time) across 2,320 companies.

**Claude Integration:** SKILL.md defines conversational profile setup, natural language job filtering, resume tailoring workflow, and LinkedIn scraping — all Claude-orchestrated.

---

## The Product Vision: Claude as the Intelligence Layer

The job board aggregates data. **Claude is the brain.**

When a user says "find me jobs," Claude should:
1. **Understand** what they want (conversational profile, not YAML editing)
2. **Find** jobs across ALL channels (JBA download + live ATS scrape + LinkedIn)
3. **Score** with intelligence (local DeepSeek LLM classifies borderline jobs)
4. **Route** to the right channel per company (knows which ATS each company uses)
5. **Present** in a dashboard with every filter a job seeker needs
6. **Help apply** — tailor resume per job, analyze skill gaps, draft cover letters

### The Intelligence Stack

```
User: "I'm a BI analyst, 5 years, want remote roles at tech companies"
  │
  ▼
Claude (SKILL.md) ─── Understands intent, builds profile
  │
  ├── JBA Download: 502K jobs from 12K companies (Greenhouse, Lever, Workday, Ashby, BambooHR)
  ├── Live Scrape: Fresh data for preferred companies
  ├── LinkedIn (G-Stack): Jobs not in ATS platforms, connection cross-ref
  │
  ▼
Rule-Based Pre-Filter: Phrase matching, location, level → ~5K candidates
  │
  ▼
Local LLM (DeepSeek on 12GB GPU): Classifies each candidate → true P1/P2/P3
  │
  ▼
Dashboard: 2,320 companies, dropdown filters, dark mode, apply links
  │
  ▼
User: "Apply to the Netflix Analytics Engineer role"
  │
  ▼
Claude: Reads job description (G-Stack browse) → Tailors resume → Saves .tex + .pdf
```

---

## Company Intelligence Routing

The key insight: **each company lives on a specific platform.** Claude should know this and route accordingly.

| Company | Primary ATS | How We Get Jobs |
|---------|-------------|-----------------|
| Netflix | Workday | JBA download + live scrape (slug: netflix\|wd1\|netflix) |
| Anthropic | Greenhouse | JBA download + live scrape (slug: anthropic) |
| Stripe | Greenhouse | JBA download + live scrape (slug: stripe) |
| LinkedIn | LinkedIn | Scrape via G-Stack browse (not in JBA) |
| Google | Own site | Not in JBA; LinkedIn scrape or Google Careers scraping |
| Apple | Own site | Same — LinkedIn or direct scraping |

When a user says "I want to work at Google," Claude should:
1. Check if Google is in JBA seed data → No (Big Tech uses own sites)
2. Check LinkedIn → Yes, scrape Google jobs from LinkedIn
3. Add Google jobs to the pipeline with `ats: "linkedin"`
4. Tell user: "Google isn't in our ATS data, but I found 47 relevant roles on LinkedIn"

When a user says "I want to work at Stripe," Claude should:
1. Check if Stripe is in JBA seed data → Yes (Greenhouse)
2. Ensure Stripe is in preferred_companies for live scraping
3. Run pipeline → fresh Stripe data
4. Tell user: "Found 11 P2+ matches at Stripe, including 'Data Analyst' posted yesterday"

---

## Local LLM Integration (DeepSeek on 12GB GPU)

The user has a local DeepSeek model on a 12GB GPU. This is a game-changer:

**Why:** Rule-based scoring can't tell "Business Intelligence Analyst" from "Market Intelligence Specialist" — the LLM can.

**How:**
1. Rule-based pre-filter reduces 502K → ~5K candidates (titles containing target keywords)
2. Local DeepSeek classifies each: "Is this job relevant for a BI analyst with 5 years Python/SQL/Tableau?"
3. Returns: relevance_score (0-100), reasoning, matched_skills
4. ~5K jobs × ~100 tokens each = ~500K tokens → feasible on 12GB GPU, ~10-30 min

**Cost:** $0 — it's local.

**Integration:**
```python
# src/llm_scorer.py
# Calls local DeepSeek via HTTP API (llama.cpp, ollama, or vllm)
# Batches 5-10 jobs per prompt for efficiency
# Stores results in data/llm_scored/YYYY-MM-DD.json
```

---

## Priority Order (What to Build Next)

### P0: Already Done ✅
- [x] 502K jobs from 12K+ companies
- [x] Phrase-based scoring (zero false positives)
- [x] Dashboard with company/location/ATS dropdown filters (2,320 companies)
- [x] GitHub Pages deployment + Actions
- [x] SKILL.md with Claude intelligence workflows

### P1: This Week
| Task | Effort | Impact |
|------|--------|--------|
| Local LLM scorer (DeepSeek) | 4 hr | Dramatically better P1/P2 quality |
| LinkedIn scraping via G-Stack | 4 hr | Jobs not in ATS (Google, Apple, etc.) |
| Resume tailoring engine | 4 hr | One-click tailored resume per job |
| Company routing intelligence in SKILL.md | 2 hr | Claude knows which platform each company uses |

### P2: Next Week
| Task | Effort | Impact |
|------|--------|--------|
| Application tracker (localStorage) | 3 hr | Applied/Skipped/Saved per job |
| LinkedIn connection cross-reference | 2 hr | "You know X at this company" |
| Skill gap analysis per job | 2 hr | "Match 8/10 requirements" |
| Daily email digest | 3 hr | P1 matches pushed to inbox |

### Kill / Defer
- ~~Streamlit~~ — Static HTML is better for GitHub Pages
- ~~Multi-user server~~ — Fork-and-customize model
- ~~Salary intelligence~~ — Not core
- ~~CF Crawl~~ — LinkedIn covers what ATS misses

---

## Key Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Companies in dashboard | 2,320 | 3,000+ (add LinkedIn) |
| P1 false positive rate | 0% | Keep at 0% |
| Time to tailored resume | Manual | < 60 seconds (Claude) |
| LLM cost | $0 | $0 (local DeepSeek) |
| Hosting cost | $0 | $0 (GitHub Pages) |
| LinkedIn integration | ❌ | ✅ |

---

*"The moat isn't the data — every job board has the same postings. The moat is the intelligence layer that matches YOU to the right job, tailors your resume, and routes you to the right channel."*
