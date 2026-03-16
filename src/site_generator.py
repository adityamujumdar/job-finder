"""Static site generator — converts scored job data to a self-contained HTML dashboard.

Generates index.html with embedded JSON data, Tailwind CSS, and vanilla JS
for search, filtering, and sorting. Designed for GitHub Pages deployment.
"""

import hashlib
import json
import logging
import html
from datetime import date
from pathlib import Path

from src.config import (
    load_profile, today, ensure_dirs,
    SCORED_DIR, REPORTS_DIR, PROJECT_ROOT,
)

log = logging.getLogger(__name__)

SITE_DIR = PROJECT_ROOT / "site"


def _load_scored_jobs(date_str: str) -> list[dict]:
    """Load scored jobs for a date, keeping only fields needed for the dashboard."""
    path = SCORED_DIR / f"{date_str}.json"
    if not path.exists():
        log.warning("No scored data for %s", date_str)
        return []

    with open(path) as f:
        jobs = json.load(f)

    # Slim down to only dashboard-relevant fields
    slim = []
    for j in jobs:
        url = j.get("url", "")
        # Stable 8-char hex ID derived from URL — lets users reference jobs by ID
        # e.g. "build resume for job a3f9c1d2"
        job_id = hashlib.sha256(url.encode()).hexdigest()[:8] if url else "00000000"
        slim.append({
            "id": job_id,
            "t": j.get("title", ""),
            "c": j.get("company", ""),
            "l": j.get("location", ""),
            "u": url,
            "s": j.get("_score", 0),
            "p": j.get("_priority", "P4"),
            "a": j.get("ats", ""),
            "lv": j.get("skill_level", ""),
            "d": (j.get("scraped_at") or "")[:10],  # date only
        })
    return slim


def _load_yesterday_ids(date_str: str) -> set[str]:
    """Load job URLs from yesterday's data to compute 'new today' badges."""
    from datetime import datetime, timedelta
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        yesterday = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return set()

    path = SCORED_DIR / f"{yesterday}.json"
    if not path.exists():
        return set()

    try:
        with open(path) as f:
            jobs = json.load(f)
        return {j.get("url", "") for j in jobs if j.get("url")}
    except Exception:
        return set()


def generate_site(date_str: str | None = None) -> str:
    """Generate static HTML dashboard.

    Returns path to generated index.html.
    """
    ensure_dirs()
    date_str = date_str or today()

    jobs = _load_scored_jobs(date_str)
    yesterday_urls = _load_yesterday_ids(date_str)

    # Mark new jobs
    for j in jobs:
        j["new"] = bool(j["u"] and j["u"] not in yesterday_urls)

    # Count stats
    p1 = sum(1 for j in jobs if j["p"] == "P1")
    p2 = sum(1 for j in jobs if j["p"] == "P2")
    p3 = sum(1 for j in jobs if j["p"] == "P3")
    new_count = sum(1 for j in jobs if j.get("new"))

    # Top companies
    from collections import Counter
    companies = Counter(j["c"] for j in jobs if j["p"] in ("P1", "P2"))
    top_companies = companies.most_common(10)

    # Load profile for display
    try:
        profile = load_profile()
        profile_name = profile.get("name", "Job Seeker")
        profile_roles = ", ".join(profile.get("target_roles", [])[:3])
    except Exception:
        profile_name = "Job Seeker"
        profile_roles = ""

    jobs_json = json.dumps(jobs, separators=(",", ":"))

    site_dir = SITE_DIR
    site_dir.mkdir(parents=True, exist_ok=True)
    output_path = site_dir / "index.html"

    html_content = _build_html(
        jobs_json=jobs_json,
        date_str=date_str,
        p1=p1, p2=p2, p3=p3,
        new_count=new_count,
        total=len(jobs),
        top_companies=top_companies,
        profile_name=profile_name,
        profile_roles=profile_roles,
    )

    output_path.write_text(html_content, encoding="utf-8")
    log.info("Site generated: %s (%d jobs, %.1f KB)",
             output_path, len(jobs), len(html_content) / 1024)

    return str(output_path)


def _build_html(*, jobs_json, date_str, p1, p2, p3, new_count, total,
                top_companies, profile_name, profile_roles) -> str:
    """Build the full HTML dashboard with company/location/ATS dropdown filters."""

    # Count unique companies and locations for stats
    import json as _json
    _jobs = _json.loads(jobs_json)
    _unique_cos = len(set(j["c"] for j in _jobs if j.get("c")))
    _unique_locs = len(set(j["l"] for j in _jobs if j.get("l")))

    return f'''<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter AI — {date_str}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {{
  darkMode: 'class',
}}
</script>
<style>
  .job-card {{ transition: all 0.15s ease; }}
  .job-card:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
  .priority-badge {{ font-size: 0.65rem; font-weight: 700; letter-spacing: 0.05em; }}
  .new-badge {{ animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
  .dropdown-panel {{ max-height: 320px; overflow-y: auto; }}
  .dropdown-panel::-webkit-scrollbar {{ width: 6px; }}
  .dropdown-panel::-webkit-scrollbar-thumb {{ background: #94a3b8; border-radius: 3px; }}
  .filter-chip {{ cursor: pointer; user-select: none; }}
  .filter-chip:hover {{ filter: brightness(0.95); }}
</style>
</head>
<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 min-h-screen">

<!-- Header -->
<header class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-50 shadow-sm">
  <div class="max-w-7xl mx-auto px-4 py-3">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold">🎯 JobHunter AI</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {html.escape(profile_roles)} • {date_str} • {_unique_cos:,} companies • {total:,} jobs
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button onclick="toggleDark()" class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700" title="Toggle dark mode">
          <span id="darkIcon">🌙</span>
        </button>
        <a href="https://github.com/adityamujumdar/job-finder" target="_blank"
           class="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200" title="Fork this repo to run it for your own job search">⭐ Fork on GitHub</a>
      </div>
    </div>
  </div>
</header>

<!-- Demo Banner -->
<div class="bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-800">
  <div class="max-w-7xl mx-auto px-4 py-2 flex items-center justify-between gap-4 text-sm">
    <span class="text-blue-700 dark:text-blue-300">
      👋 <strong>This is a sample dashboard</strong> — jobs shown are matched to a real profile.
      Fork the repo and set it up with your own profile to see <em>your</em> matches.
    </span>
    <a href="https://github.com/adityamujumdar/job-finder#get-started-in-3-steps-10-minutes"
       target="_blank"
       class="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline">Set it up → </a>
  </div>
</div>

<!-- Stats Bar -->
<div class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
  <div class="max-w-7xl mx-auto px-4 py-2">
    <div class="flex flex-wrap gap-3 items-center">
      <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300" title="P1: Apply today — strong match (score 85–100)">🔴 P1 <span class="font-normal ml-1 hidden sm:inline">apply today</span> · {p1}</span>
      <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300" title="P2: Apply this week — good match (score 70–84)">🟠 P2 <span class="font-normal ml-1 hidden sm:inline">this week</span> · {p2}</span>
      <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300" title="P3: Apply if you have time — decent match (score 50–69)">🟡 P3 <span class="font-normal ml-1 hidden sm:inline">if time</span> · {p3}</span>
      {f'<span class="text-green-600 dark:text-green-400 text-xs font-medium">{new_count} new ⭐</span>' if new_count else ''}
      <span id="count" class="text-xs text-gray-500 dark:text-gray-400 ml-auto"></span>
    </div>
  </div>
</div>

<!-- Filter Bar -->
<div class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
  <div class="max-w-7xl mx-auto px-4 py-3">
    <!-- Row 1: Search + Priority + New + Sort -->
    <div class="flex flex-wrap gap-2 items-center">
      <div class="relative flex-1 min-w-[180px] max-w-sm">
        <input type="text" id="search" placeholder="Search jobs, companies, locations..."
               class="w-full pl-9 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
               oninput="filterJobs()">
        <svg class="absolute left-3 top-2.5 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
      </div>
      <div class="flex gap-1">
        <button onclick="togglePriority('P1')" id="btn-P1" class="filter-chip px-3 py-1.5 rounded-lg text-xs font-bold bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300 border-2 border-red-300 dark:border-red-700" title="P1: Apply today — your strongest matches">🔴 P1 <span class="font-normal hidden sm:inline">today</span></button>
        <button onclick="togglePriority('P2')" id="btn-P2" class="filter-chip px-3 py-1.5 rounded-lg text-xs font-bold bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300 border-2 border-orange-300 dark:border-orange-700" title="P2: Apply this week — good matches">🟠 P2 <span class="font-normal hidden sm:inline">this week</span></button>
        <button onclick="togglePriority('P3')" id="btn-P3" class="filter-chip px-3 py-1.5 rounded-lg text-xs font-bold bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300 border-2 border-yellow-300 dark:border-yellow-700" title="P3: Apply if you have time — decent matches">🟡 P3 <span class="font-normal hidden sm:inline">if time</span></button>
      </div>
      <button onclick="toggleNew()" id="btn-new" class="filter-chip px-3 py-1.5 rounded-lg text-xs font-medium border-2 border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300">⭐ New</button>
      <select id="sort" onchange="filterJobs()" class="px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800">
        <option value="score">Score ↓</option>
        <option value="company">Company A-Z</option>
        <option value="title">Title A-Z</option>
        <option value="date">Date ↓</option>
      </select>
    </div>

    <!-- Row 2: Company, Location, ATS dropdowns -->
    <div class="flex flex-wrap gap-2 mt-2 items-center">
      <!-- Company Dropdown -->
      <div class="relative" id="company-dropdown-wrap">
        <button onclick="toggleDropdown('company')" id="company-dropdown-btn"
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700">
          <span>🏢 Company</span>
          <span id="company-badge" class="hidden px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 font-bold text-[10px]">0</span>
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="company-panel" class="hidden absolute left-0 top-full mt-1 w-72 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-40">
          <div class="p-2 border-b border-gray-200 dark:border-gray-700">
            <input type="text" id="company-search" placeholder="Search companies..."
                   class="w-full px-3 py-1.5 rounded text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
                   oninput="filterCompanyList()">
          </div>
          <div class="p-1 border-b border-gray-200 dark:border-gray-700 flex gap-1">
            <button onclick="selectAllCompanies()" class="text-[10px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600">All</button>
            <button onclick="clearAllCompanies()" class="text-[10px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600">None</button>
          </div>
          <div id="company-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- Location Dropdown -->
      <div class="relative" id="location-dropdown-wrap">
        <button onclick="toggleDropdown('location')" id="location-dropdown-btn"
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700">
          <span>📍 Location</span>
          <span id="location-badge" class="hidden px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 font-bold text-[10px]">0</span>
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="location-panel" class="hidden absolute left-0 top-full mt-1 w-72 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-40">
          <div class="p-2 border-b border-gray-200 dark:border-gray-700">
            <input type="text" id="location-search" placeholder="Search locations..."
                   class="w-full px-3 py-1.5 rounded text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
                   oninput="filterLocationList()">
          </div>
          <div class="p-1 border-b border-gray-200 dark:border-gray-700 flex gap-1">
            <button onclick="selectAllLocations()" class="text-[10px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600">All</button>
            <button onclick="clearAllLocations()" class="text-[10px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600">None</button>
          </div>
          <div id="location-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- ATS Platform Dropdown -->
      <div class="relative" id="ats-dropdown-wrap">
        <button onclick="toggleDropdown('ats')" id="ats-dropdown-btn"
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700">
          <span>⚡ Platform</span>
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="ats-panel" class="hidden absolute left-0 top-full mt-1 w-52 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-40">
          <div id="ats-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- Active filter chips -->
      <div id="active-filters" class="flex flex-wrap gap-1 ml-2"></div>

      <button onclick="resetAllFilters()" id="reset-btn" class="hidden text-xs text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 underline ml-auto">
        Clear all filters
      </button>
    </div>
  </div>
</div>

<!-- Claude Tip -->
<div class="max-w-7xl mx-auto px-4 pt-3">
  <div class="bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-lg px-4 py-2 text-xs text-purple-700 dark:text-purple-300 flex items-center gap-2">
    <span>🤖</span>
    <span><strong>Using Claude Code?</strong> Each card has a Job ID (e.g. <code class="font-mono bg-purple-100 dark:bg-purple-900/40 px-1 rounded">#a3f9c1d2</code>).
    Tell Claude: <em>"build a resume for job #a3f9c1d2"</em> or <em>"classify my P1 jobs"</em> using <code class="font-mono bg-purple-100 dark:bg-purple-900/40 px-1 rounded">/classify-jobs</code></span>
  </div>
</div>

<!-- Job Cards -->
<div class="max-w-7xl mx-auto px-4 py-4 pb-8">
  <div id="jobs" class="grid gap-3"></div>
  <div id="empty" class="hidden text-center py-20 text-gray-400 dark:text-gray-500">
    <p class="text-4xl mb-4">🔍</p>
    <p class="text-lg">No jobs match your filters</p>
    <p class="text-sm mt-1">Try broadening your search or clearing filters</p>
  </div>
  <div id="load-more-container" class="text-center py-4 hidden">
    <button onclick="loadMore()" id="load-more-btn"
            class="px-6 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700">Load More</button>
  </div>
</div>

<!-- Footer -->
<footer class="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 py-6">
  <div class="max-w-7xl mx-auto px-4 text-center text-sm text-gray-500 dark:text-gray-400">
    <p>Built with ❤️ using <a href="https://github.com/Feashliaa/job-board-aggregator" class="underline hover:text-gray-700 dark:hover:text-gray-200">job-board-aggregator</a> (MIT) • Data from 12,000+ companies across Greenhouse, Lever, Workday, Ashby, BambooHR</p>
    <p class="mt-1"><a href="https://github.com/adityamujumdar/job-finder" class="underline hover:text-gray-700 dark:hover:text-gray-200">Source Code (MIT License)</a> • Made for job seekers, by job seekers</p>
  </div>
</footer>

<script>
// ── Data ──
const ALL_JOBS = {jobs_json};
let filtered = [...ALL_JOBS];
let activePriorities = new Set(["P1", "P2", "P3"]);
// null = no filter (show all); empty Set = explicit "show none"; non-empty Set = filter to these
let selectedCompanies = null;
let selectedLocations = null;
let selectedATS = new Set(); // empty = all (ATS has no None button)
let newOnly = false;
let PAGE_SIZE = 50;
let shown = 0;

// ── Build filter options from data ──
const companyMap = {{}};  // company -> count
const locationMap = {{}};
const atsMap = {{}};

ALL_JOBS.forEach(j => {{
  if (j.c) companyMap[j.c] = (companyMap[j.c]||0) + 1;
  if (j.l) {{
    // Simplify location: keep first meaningful part
    let loc = j.l.includes('Remote') ? 'Remote' : j.l.split(',').slice(0,2).join(',').trim();
    if (loc.length > 40) loc = loc.substring(0, 40);
    locationMap[loc] = (locationMap[loc]||0) + 1;
  }}
  if (j.a) atsMap[j.a] = (atsMap[j.a]||0) + 1;
}});

// Sort by count descending
const companiesSorted = Object.entries(companyMap).sort((a,b) => b[1]-a[1]);
const locationsSorted = Object.entries(locationMap).sort((a,b) => b[1]-a[1]);
const atsSorted = Object.entries(atsMap).sort((a,b) => b[1]-a[1]);

// ── Priority colors ──
const PC = {{
  P1: {{ card: "border-l-4 border-l-red-500 bg-white dark:bg-gray-800", badge: "bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300" }},
  P2: {{ card: "border-l-4 border-l-orange-500 bg-white dark:bg-gray-800", badge: "bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300" }},
  P3: {{ card: "border-l-4 border-l-yellow-500 bg-white dark:bg-gray-800", badge: "bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300" }},
}};

// ── Render ──
function esc(s) {{ return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : ''; }}

function renderCard(j) {{
  const pc = PC[j.p] || PC.P3;
  const newBadge = j.new ? '<span class="new-badge inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300 ml-1">NEW ⭐</span>' : '';
  return `<div class="job-card ${{pc.card}} rounded-lg shadow-sm p-4 hover:shadow-md">
    <div class="flex items-start justify-between gap-3">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="priority-badge px-1.5 py-0.5 rounded ${{pc.badge}}">${{j.p}}</span>
          <span class="text-xs text-gray-400 dark:text-gray-500">${{j.s.toFixed(1)}}</span>
          ${{newBadge}}
          ${{j.a ? '<span class="text-[10px] uppercase text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">' + esc(j.a) + '</span>' : ''}}
        </div>
        <h3 class="mt-1 font-semibold text-sm leading-tight" title="${{esc(j.t)}}">${{esc(j.t)}}</h3>
        <p class="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
          <span class="font-medium cursor-pointer hover:text-blue-600 dark:hover:text-blue-400" onclick="filterByCompany('${{esc(j.c)}}')">${{esc(j.c)}}</span>
          ${{j.l ? ' • <span class="cursor-pointer hover:text-blue-600 dark:hover:text-blue-400" onclick="filterByLocation(\\'' + esc(j.l) + '\\')">' + esc(j.l) + '</span>' : ''}}
        </p>
        <div class="flex items-center gap-2 mt-1 text-xs text-gray-400 dark:text-gray-500">
          ${{j.lv ? '<span>' + esc(j.lv) + '</span>' : ''}}
          ${{j.d ? '<span>' + j.d + '</span>' : ''}}
          <span class="font-mono text-[10px] text-gray-300 dark:text-gray-600 select-all" title="Job ID — tell Claude: build resume for job ${{j.id}}">#${{j.id}}</span>
        </div>
      </div>
      ${{j.u ? `<a href="${{j.u}}" target="_blank" rel="noopener" class="shrink-0 inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors">Apply ↗</a>` : ''}}
    </div>
  </div>`;
}}

function renderJobs() {{
  const container = document.getElementById('jobs');
  const empty = document.getElementById('empty');
  const loadMoreC = document.getElementById('load-more-container');
  const countEl = document.getElementById('count');

  if (filtered.length === 0) {{
    container.innerHTML = '';
    empty.classList.remove('hidden');
    loadMoreC.classList.add('hidden');
    countEl.textContent = '0 jobs';
    return;
  }}

  empty.classList.add('hidden');
  shown = Math.min(PAGE_SIZE, filtered.length);
  container.innerHTML = filtered.slice(0, shown).map(renderCard).join('');

  if (shown < filtered.length) {{
    loadMoreC.classList.remove('hidden');
    document.getElementById('load-more-btn').textContent = `Load More (${{filtered.length - shown}} remaining)`;
  }} else {{ loadMoreC.classList.add('hidden'); }}

  // Count companies in filtered results
  const fCos = new Set(filtered.map(j => j.c).filter(Boolean));
  countEl.textContent = `${{filtered.length}} jobs · ${{fCos.size}} companies`;
}}

function loadMore() {{
  const container = document.getElementById('jobs');
  const loadMoreC = document.getElementById('load-more-container');
  const next = Math.min(shown + PAGE_SIZE, filtered.length);
  container.innerHTML += filtered.slice(shown, next).map(renderCard).join('');
  shown = next;
  if (shown >= filtered.length) {{ loadMoreC.classList.add('hidden'); }}
  else {{ document.getElementById('load-more-btn').textContent = `Load More (${{filtered.length - shown}} remaining)`; }}
}}

// ── Filtering ──
function filterJobs() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  const sort = document.getElementById('sort').value;

  filtered = ALL_JOBS.filter(j => {{
    if (!activePriorities.has(j.p)) return false;
    if (newOnly && !j.new) return false;
    // null = show all; empty Set = show none; non-empty Set = filter to these
    if (selectedCompanies !== null && !selectedCompanies.has(j.c)) return false;
    if (selectedLocations !== null) {{
      let loc = j.l ? (j.l.includes('Remote') ? 'Remote' : j.l.split(',').slice(0,2).join(',').trim()) : '';
      if (loc.length > 40) loc = loc.substring(0, 40);
      if (!selectedLocations.has(loc)) return false;
    }}
    if (selectedATS.size > 0 && !selectedATS.has(j.a)) return false;
    if (q) {{
      const hay = (j.t + ' ' + j.c + ' ' + j.l + ' ' + j.a).toLowerCase();
      return q.split(/\\s+/).every(w => hay.includes(w));
    }}
    return true;
  }});

  switch(sort) {{
    case 'score': filtered.sort((a,b) => b.s - a.s); break;
    case 'company': filtered.sort((a,b) => a.c.localeCompare(b.c)); break;
    case 'title': filtered.sort((a,b) => a.t.localeCompare(b.t)); break;
    case 'date': filtered.sort((a,b) => b.d.localeCompare(a.d)); break;
  }}

  renderJobs();
  updateActiveFilters();
  updateResetBtn();
}}

// ── Priority toggles ──
function togglePriority(p) {{
  const btn = document.getElementById('btn-' + p);
  if (activePriorities.has(p)) {{ activePriorities.delete(p); btn.style.opacity = '0.4'; }}
  else {{ activePriorities.add(p); btn.style.opacity = '1'; }}
  filterJobs();
}}

function toggleNew() {{
  newOnly = !newOnly;
  document.getElementById('btn-new').style.opacity = newOnly ? '1' : '0.5';
  filterJobs();
}}

// ── Dropdown panels ──
let openDropdown = null;

function toggleDropdown(which) {{
  const panel = document.getElementById(which + '-panel');
  if (openDropdown && openDropdown !== which) {{
    document.getElementById(openDropdown + '-panel').classList.add('hidden');
  }}
  panel.classList.toggle('hidden');
  openDropdown = panel.classList.contains('hidden') ? null : which;
}}

document.addEventListener('click', e => {{
  if (openDropdown) {{
    const wrap = document.getElementById(openDropdown + '-dropdown-wrap');
    if (wrap && !wrap.contains(e.target)) {{
      document.getElementById(openDropdown + '-panel').classList.add('hidden');
      openDropdown = null;
    }}
  }}
}});

// ── Company dropdown ──
function buildCompanyList(filter = '') {{
  const list = document.getElementById('company-list');
  const fl = filter.toLowerCase();
  const items = companiesSorted.filter(([name]) => !fl || name.toLowerCase().includes(fl));
  list.innerHTML = items.slice(0, 200).map(([name, count]) => {{
    // null = all checked; non-null Set = only checked if in Set
    const checked = selectedCompanies === null || selectedCompanies.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleCompany('${{esc(name)}}')" class="rounded text-blue-600">
      <span class="flex-1 truncate">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('') + (items.length > 200 ? '<p class="text-[10px] text-gray-400 px-2 py-1">Showing 200 of ' + items.length + ' — search to narrow</p>' : '');
}}

function filterCompanyList() {{ buildCompanyList(document.getElementById('company-search').value); }}

function toggleCompany(name) {{
  if (selectedCompanies === null) {{
    // Was "show all" — transition to "show only this one"
    selectedCompanies = new Set([name]);
  }} else if (selectedCompanies.has(name)) {{
    selectedCompanies.delete(name);
  }} else {{
    selectedCompanies.add(name);
  }}
  updateCompanyBadge();
  buildCompanyList();
  filterJobs();
}}

function filterByCompany(name) {{
  selectedCompanies = new Set([name]);
  updateCompanyBadge();
  buildCompanyList();
  filterJobs();
}}

// All = no filter (show everything); None = empty Set (show nothing)
function selectAllCompanies() {{ selectedCompanies = null; updateCompanyBadge(); buildCompanyList(); filterJobs(); }}
function clearAllCompanies() {{ selectedCompanies = new Set(); updateCompanyBadge(); buildCompanyList(); filterJobs(); }}

function updateCompanyBadge() {{
  const badge = document.getElementById('company-badge');
  // Show badge only when a specific selection is active (not null = all)
  if (selectedCompanies !== null && selectedCompanies.size > 0) {{
    badge.textContent = selectedCompanies.size;
    badge.classList.remove('hidden');
  }} else {{ badge.classList.add('hidden'); }}
}}

// ── Location dropdown ──
function buildLocationList(filter = '') {{
  const list = document.getElementById('location-list');
  const fl = filter.toLowerCase();
  const items = locationsSorted.filter(([name]) => !fl || name.toLowerCase().includes(fl));
  list.innerHTML = items.slice(0, 150).map(([name, count]) => {{
    // null = all checked; non-null Set = only checked if in Set
    const checked = selectedLocations === null || selectedLocations.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleLocation('${{esc(name)}}')" class="rounded text-blue-600">
      <span class="flex-1 truncate">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('');
}}

function filterLocationList() {{ buildLocationList(document.getElementById('location-search').value); }}

function toggleLocation(name) {{
  if (selectedLocations === null) {{
    // Was "show all" — transition to "show only this one"
    selectedLocations = new Set([name]);
  }} else if (selectedLocations.has(name)) {{
    selectedLocations.delete(name);
  }} else {{
    selectedLocations.add(name);
  }}
  updateLocationBadge();
  buildLocationList();
  filterJobs();
}}

function filterByLocation(name) {{
  let loc = name.includes('Remote') ? 'Remote' : name.split(',').slice(0,2).join(',').trim();
  if (loc.length > 40) loc = loc.substring(0, 40);
  selectedLocations = new Set([loc]);
  updateLocationBadge();
  buildLocationList();
  filterJobs();
}}

// All = no filter (show everything); None = empty Set (show nothing)
function selectAllLocations() {{ selectedLocations = null; updateLocationBadge(); buildLocationList(); filterJobs(); }}
function clearAllLocations() {{ selectedLocations = new Set(); updateLocationBadge(); buildLocationList(); filterJobs(); }}

function updateLocationBadge() {{
  const badge = document.getElementById('location-badge');
  if (selectedLocations !== null && selectedLocations.size > 0) {{
    badge.textContent = selectedLocations.size;
    badge.classList.remove('hidden');
  }} else {{ badge.classList.add('hidden'); }}
}}

// ── ATS dropdown ──
function buildATSList() {{
  const list = document.getElementById('ats-list');
  list.innerHTML = atsSorted.map(([name, count]) => {{
    const checked = selectedATS.size === 0 || selectedATS.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleATS('${{esc(name)}}')" class="rounded text-blue-600">
      <span class="flex-1 uppercase">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('');
}}

function toggleATS(name) {{
  if (selectedATS.has(name)) {{ selectedATS.delete(name); }}
  else {{ selectedATS.add(name); }}
  filterJobs();
}}

// ── Active filter chips display ──
function updateActiveFilters() {{
  const container = document.getElementById('active-filters');
  let chips = [];
  if (selectedCompanies !== null) {{
    selectedCompanies.forEach(c => {{
      chips.push(`<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300">
        🏢 ${{esc(c)}} <button onclick="selectedCompanies.delete('${{esc(c)}}'); updateCompanyBadge(); buildCompanyList(); filterJobs();" class="ml-0.5 hover:text-red-500">✕</button></span>`);
    }});
  }}
  if (selectedLocations !== null) {{
    selectedLocations.forEach(l => {{
      chips.push(`<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300">
        📍 ${{esc(l)}} <button onclick="selectedLocations.delete('${{esc(l)}}'); updateLocationBadge(); buildLocationList(); filterJobs();" class="ml-0.5 hover:text-red-500">✕</button></span>`);
    }});
  }}
  container.innerHTML = chips.join('');
}}

function updateResetBtn() {{
  const btn = document.getElementById('reset-btn');
  // null = no filter; non-null (even empty Set) = active filter
  const hasFilters = selectedCompanies !== null || selectedLocations !== null || selectedATS.size > 0 || newOnly;
  btn.classList.toggle('hidden', !hasFilters);
}}

function resetAllFilters() {{
  selectedCompanies = null; selectedLocations = null; selectedATS.clear();
  newOnly = false;
  activePriorities = new Set(["P1","P2","P3"]);
  document.getElementById('search').value = '';
  document.getElementById('btn-new').style.opacity = '0.5';
  ['P1','P2','P3'].forEach(p => document.getElementById('btn-' + p).style.opacity = '1');
  updateCompanyBadge(); updateLocationBadge();
  buildCompanyList(); buildLocationList(); buildATSList();
  filterJobs();
}}

// ── Dark mode ──
function toggleDark() {{
  document.documentElement.classList.toggle('dark');
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('dark', isDark);
  document.getElementById('darkIcon').textContent = isDark ? '☀️' : '🌙';
}}

if (localStorage.getItem('dark') === 'true' || (!localStorage.getItem('dark') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {{
  document.documentElement.classList.add('dark');
  document.getElementById('darkIcon').textContent = '☀️';
}}

// ── Init ──
document.getElementById('btn-new').style.opacity = '0.5';
buildCompanyList();
buildLocationList();
buildATSList();
filterJobs();
</script>
</body>
</html>'''


# ── CLI ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="JobHunter static site generator")
    parser.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD)")
    args = parser.parse_args()

    path = generate_site(date_str=args.date)
    print(f"\n✅ Site generated: {path}")
