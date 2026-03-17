# 🎯 JobHunter AI

**Stop scrolling job boards. Tell Claude what you're looking for — it searches 502,000+ jobs, scores every match, and gets your resume ready to send.**

> 🤖 **You'll need [Claude Code](https://claude.ai/code)** — it's the AI assistant that runs everything here. Free with a Claude account. [Get it →](https://claude.ai/code)

[**→ See a Live Dashboard Example**](https://adityamujumdar.github.io/job-finder)

---

## What You'll Get

Every time you run it, JobHunter searches over **half a million job listings** from 12,000+ companies, scores each one against your background, and shows you a ranked dashboard:

```
🔴 P1 — Apply today      ← Your best matches. Strong fit. Do these first.
🟠 P2 — Apply this week  ← Good matches. Worth your time.
🟡 P3 — If you have time ← Decent match. Apply if you're being thorough.
```

Then Claude helps you act on the best ones:

```
You    →  /classify-jobs
Claude →  "You have 8 P1 jobs. Apply to Stripe first — your Python + distributed
           systems background is exactly what they listed. Here's why each one
           is or isn't worth your time..."

You    →  "build a resume for job #a3f9c1d2"
Claude →  [tailors your resume to that specific job, opens in browser]
You    →  Cmd+P → PDF saved ✅
```

---

## Before You Start

You need two things (both free):

| | What | Why you need it | Get it |
|---|---|---|---|
| 🤖 | **Claude Code** | The AI that runs JobHunter for you | [claude.ai/code](https://claude.ai/code) |
| 🐙 | **GitHub account** | Where your dashboard gets hosted | [github.com](https://github.com) — 30 seconds to sign up |

---

## Get Started (~5 minutes)

### Step 1 — Open Claude Code and paste this

```
git clone https://github.com/adityamujumdar/job-finder.git ~/job-finder 2>/dev/null || (cd ~/job-finder && git pull); cd ~/job-finder && ./setup
```

Claude installs everything, registers the skills, then asks what kind of jobs you're looking for:

```
╔══════════════════════════════════════════════════════════════════╗
║  Claude Code                                                      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ✅ JobHunter AI is ready!                                       ║
║                                                                  ║
║  Available skills:                                               ║
║     /jobhunter        → find and score 502K+ jobs                ║
║     /classify-jobs    → rank matches: APPLY NOW / THIS WEEK      ║
║     /tailor-resume    → build a tailored resume for a job        ║
║                                                                  ║
║  💡 Type /jobhunter to start your job search!                    ║
║                                                                  ║
║  You: /jobhunter                                                 ║
║                                                                  ║
║  Claude: Hi! I'll help you find jobs. Let me set up your        ║
║          profile first.                                          ║
║                                                                  ║
║          What kind of roles are you looking for?                 ║
║          (e.g. "Software Engineer", "Product Manager",           ║
║           "Data Analyst", "Marketing Manager")                   ║
║                                                                  ║
║  You: Software Engineer, Backend Engineer                        ║
║                                                                  ║
║  Claude: Where are you based? Open to remote or relocation?     ║
║                                                                  ║
║  You: Austin, TX — open to remote and SF                        ║
║                                                                  ║
║  Claude: How many years of experience do you have?              ║
║                                                                  ║
║  You: 4 years                                                    ║
║                                                                  ║
║  Claude: Any companies you'd love to work at?                   ║
║                                                                  ║
║  You: Stripe, Anthropic, Linear                                  ║
║                                                                  ║
║  Claude: ✅ Profile saved. Running the job search...            ║
║          Downloading 502K jobs... done (15s)                     ║
║          Scoring against your profile... done (8s)               ║
║          Generating dashboard... done                            ║
║                                                                  ║
║          🎯 Found 23 P1 jobs — apply today!                     ║
║             + 156 P2 matches worth applying this week            ║
║             Dashboard → site/index.html                          ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

> **You don't need to edit any config files.** Claude handles everything for you.

---

### Step 2 — See Your Jobs (instant)

Claude opens (or tells you to open) `site/index.html` in your browser. Here's what you'll see:

```
┌────────────────────────────────────────────────────────────────────────┐
│  🎯 JobHunter AI                              [🌙 Dark mode]           │
│  Software Engineer roles · 23 P1 · 156 P2 · 891 P3 · 48 new ⭐       │
│  ─────────────────────────────────────────────────────────────────────│
│  🔍 Search jobs, companies, locations...                               │
│  [🔴 P1 — today] [🟠 P2 — this week] [🟡 P3 — if time] [⭐ New]      │
│  ─────────────────────────────────────────────────────────────────────│
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 🔴 P1  93.2  NEW ⭐  greenhouse                                   │  │
│  │ Senior Software Engineer                                          │  │
│  │ Stripe  •  San Francisco, CA                         [Apply ↗]   │  │
│  │ senior  •  posted 3 days ago  •  #a3f9c1d2 ◄─── Job ID          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│       ↑                                  ↑                             │
│  Red = strong match,             Use the ID to ask Claude:             │
│  apply today                     "build a resume for job #a3f9c1d2"    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 🔴 P1  91.7  NEW ⭐  greenhouse                                   │  │
│  │ Backend Engineer                                                  │  │
│  │ Anthropic  •  San Francisco, CA                      [Apply ↗]   │  │
│  │ senior  •  posted 1 day ago  •  #b7e2f4a9                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  [Load More (154 remaining)]                                           │
└────────────────────────────────────────────────────────────────────────┘
```

Click **[Apply ↗]** to open the job page. Click a company name to filter to that company. Search anything in the search box. That's all you need to know.

---

## Using Claude Every Day

Once set up, you just talk to Claude. Here are the three things you'll do most:

---

### 🔍 Find new jobs

```
/jobhunter
```

Claude runs the search and shows your latest matches.

---

### 📋 Decide what to apply to

```
/classify-jobs
```

Claude goes through your P1 and P2 jobs and sorts them into:

```
✅ APPLY NOW  — do this tonight, you're a strong fit
📅 THIS WEEK  — good match, block time for this
🔼 STRETCH    — reach role, worth trying anyway
⏭️  SKIP       — not the right fit, don't waste time
```

---

### 📄 Get a resume for a specific job

Copy the job ID from the dashboard (the `#a3f9c1d2` part on each card) and say:

```
/tailor-resume
build a resume for job #a3f9c1d2
```

Claude reads the job description + your background → generates a polished, job-specific resume → opens it in your browser → Cmd+P (Mac) or Ctrl+P (Windows) to save as PDF.

**The whole thing takes about 30 seconds.**

---

### 💬 Ask Claude anything

```
"Which of my P1 jobs should I apply to first?"
"What's missing from my background for the Stripe role?"
"Tell me more about job #b7e2f4a9 — is it worth my time?"
"Add React to my skills and re-run the search"
"Are there any machine learning roles I'm missing?"
```

Claude knows your profile, your resume, and all your matched jobs. Just talk to it.

---

## Set It and Forget It (Automatic Daily Updates)

You can have the job dashboard refresh automatically every morning:

**1.** Push the repo to your GitHub account:
```bash
cd ~/job-finder
git remote set-url origin https://github.com/YOUR-USERNAME/job-finder.git
git push -u origin main
```

**2.** On GitHub, go to your repo → **Settings** → **Pages** → **Source: GitHub Actions** → Save

**3.** Done ✅

Your dashboard now updates at **6am UTC every day** and lives at:
```
https://YOUR-USERNAME.github.io/job-finder
```

No clicking. No remembering. Just check your URL each morning.

---

## Common Questions

**"Do I need to know how to code?"**
Not at all. You paste one line into Claude Code and it handles everything.

**"Is this free?"**
Yes. Job data is open-source, GitHub hosting is free, and Claude is included in your existing plan. Total cost: $0.

**"Will it find jobs for my specific field?"**
Yes — Claude sets up your profile around your target roles (Step 1). A designer will see design jobs; a PM will see PM jobs. If results aren't great, tell Claude: *"Help me tune my profile, I'm not seeing the right jobs."*

**"Is my resume private?"**
Yes. Your resume (`RESUME.md`) stays on your computer and is never uploaded to GitHub or anywhere else.

**"Can I search for jobs at a specific company?"**
Yes. In the dashboard, click any company name to filter to just that company. Or ask Claude: *"Show me all the Stripe jobs I matched."*

**"My results aren't great. What do I do?"**
Tell Claude: *"I'm getting mostly P3 jobs. Can you help me tune my profile?"* It'll ask questions and adjust your settings.

---

## How the Scoring Works

Each job gets a score from 0–100 based on how well it matches your profile:

| What gets scored | Weight | Example |
|---|---|---|
| Job title vs. your target roles | 35% | "Senior Software Engineer" matches "Software Engineer" |
| Location vs. where you're based | 20% | Remote-OK roles score high if you're remote-open |
| Seniority level | 15% | "Senior" matches if you said 4+ years experience |
| Keywords in the job description | 15% | Boost for Python, Go, distributed systems, etc. |
| Preferred companies | 10% | Stripe, Anthropic, Linear get a boost |
| How recently posted | 5% | Brand new listings score slightly higher |

P1 = scored 85–100 · P2 = 70–84 · P3 = 50–69

---

## Technical Details (for the curious)

<details>
<summary>Architecture, file structure, ATS platforms covered, and advanced config</summary>

### How it works under the hood

```
DAILY PIPELINE (runs automatically via GitHub Actions)
────────────────────────────────────────────────────

  src/downloader.py     Download 502K jobs from job-board-aggregator (~15s)
         ↓
  src/scraper.py        Merge + deduplicate + clean
         ↓
  src/matcher.py        Score every job against profile.yaml (~8s)
         ↓
  src/report.py         CSV report + terminal summary
         ↓
  src/site_generator.py Build the HTML dashboard
         ↓
  GitHub Pages          Deployed automatically
```

### ATS platforms covered

Greenhouse, Lever, Workday, Ashby, BambooHR — 12,000+ companies total.

### File structure

```
job-finder/
├── config/
│   ├── profile.yaml          # Your preferences (edit this or let Claude do it)
│   └── profile.yaml.example  # Template
├── src/                      # Python pipeline
│   ├── scraper.py            # Orchestrator: download + merge
│   ├── matcher.py            # Score jobs against your profile
│   ├── report.py             # CSV + terminal summary
│   └── site_generator.py     # HTML dashboard builder
├── jobhunter/SKILL.md        # /jobhunter Claude skill
├── classify-jobs/SKILL.md    # /classify-jobs Claude skill
├── tailor-resume/SKILL.md    # /tailor-resume Claude skill
├── RESUME.md                 # Your resume in Markdown (gitignored — stays local)
├── RESUME.md.example         # Template: copy to RESUME.md and fill in
└── .github/workflows/
    └── daily.yml             # Runs pipeline daily at 6am UTC
```

### Running the pipeline manually

```bash
source .venv/bin/activate
python -m src.scraper           # Download & merge 502K jobs (~25s)
python -m src.matcher           # Score & rank against your profile (~8s)
python -m src.report            # CSV report + terminal summary
python -m src.site_generator    # Generate HTML dashboard
open site/index.html            # View dashboard
```

### LLM upgrade path

| Scorer | Status | How |
|--------|--------|-----|
| **Claude** (default) | ✅ Works now | Load SKILL.md → talk to Claude |
| **Ollama/DeepSeek** (local GPU) | 🔜 Planned | `src/llm_scorer.py` (not yet built) |

</details>

---

## Credits

Built on [job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) (MIT) — the open-source dataset that makes 502K+ daily jobs possible.

---

## License

[MIT](LICENSE) — Fork it, customize it, share it.

*If this helps you land a role, star the repo ⭐*
