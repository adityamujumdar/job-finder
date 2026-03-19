"""Static site generator — converts scored job data to a self-contained HTML dashboard.

Generates index.html with embedded JSON data, Tailwind CSS, and vanilla JS
for search, filtering, and sorting. Designed for GitHub Pages deployment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import html
from datetime import date
from pathlib import Path

from src.config import (
    load_profile, profile_hash, today, ensure_dirs,
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


def _check_staleness(date_str: str) -> dict:
    """Check if scored data matches the current profile.

    Compares profile_hash() (current profile) against the hash stored
    in the .meta.json sidecar written by matcher.run_matcher().

    Returns dict with:
      - "status": "fresh" | "stale" | "unknown"
      - "stored_hash": str or None
      - "current_hash": str
      - "stored_roles": list or None
    """
    current_hash = profile_hash()
    meta_path = SCORED_DIR / f"{date_str}.meta.json"

    if not meta_path.exists():
        return {
            "status": "unknown",
            "stored_hash": None,
            "current_hash": current_hash,
            "stored_roles": None,
        }

    try:
        with open(meta_path) as f:
            meta = json.load(f)
        stored_hash = meta.get("profile_hash", "")
        stored_roles = meta.get("target_roles", [])
        status = "fresh" if stored_hash == current_hash else "stale"
        return {
            "status": status,
            "stored_hash": stored_hash,
            "current_hash": current_hash,
            "stored_roles": stored_roles,
        }
    except (json.JSONDecodeError, OSError, KeyError):
        return {
            "status": "unknown",
            "stored_hash": None,
            "current_hash": current_hash,
            "stored_roles": None,
        }


def generate_site(date_str: str | None = None) -> str:
    """Generate static HTML dashboard.

    Returns path to generated index.html.
    """
    ensure_dirs()
    date_str = date_str or today()

    jobs = _load_scored_jobs(date_str)
    yesterday_urls = _load_yesterday_ids(date_str)

    # Mark new jobs — only when yesterday's data actually exists.
    # Without it every job would appear "new" (empty set → always not-in).
    has_yesterday = bool(yesterday_urls)
    for j in jobs:
        j["new"] = bool(has_yesterday and j["u"] and j["u"] not in yesterday_urls)

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

    # Check profile staleness — warn only, do NOT auto-rescore.
    # Rescoring is the SKILL.md orchestration layer's job, not site_generator's.
    # This keeps the dependency graph clean: site_generator never imports matcher.
    staleness = _check_staleness(date_str)
    if staleness["status"] == "stale":
        log.warning("Profile changed since last score (stored: %s, current: %s). "
                    "Dashboard may show stale results. Re-run: python -m src.matcher",
                    staleness["stored_hash"], staleness["current_hash"])
    elif staleness["status"] == "unknown":
        log.warning("No meta file for %s — cannot verify profile match.", date_str)

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
        staleness_status=staleness["status"],
    )

    output_path.write_text(html_content, encoding="utf-8")
    log.info("Site generated: %s (%d jobs, %.1f KB)",
             output_path, len(jobs), len(html_content) / 1024)

    return str(output_path)


def _build_html(*, jobs_json, date_str, p1, p2, p3, new_count, total,
                top_companies, profile_name, profile_roles,
                staleness_status="unknown") -> str:
    """Build the full HTML dashboard — clean, minimal, job-focused."""

    import json as _json
    _jobs = _json.loads(jobs_json)
    _unique_cos = len(set(j["c"] for j in _jobs if j.get("c")))

    # Header subtitle: staleness indicator · roles · P1/P2/P3 counts · new · date
    #   fresh   → "✅ BI Developer, Data Analyst · 51 P1 · 1188 P2 · ..."
    #   stale   → "⚠️ Stale — profile changed · 51 P1 · ..."
    #   unknown → "BI Developer, Data Analyst · 51 P1 · ..."  (no indicator)
    stats_parts = [f"{p1} P1", f"{p2} P2", f"{p3} P3"]
    if new_count:
        stats_parts.append(f"{new_count} new today")
    stats_str = " · ".join(stats_parts) + f" · {date_str}"

    if staleness_status == "fresh":
        roles_display = f"✅ {html.escape(profile_roles)}" if profile_roles else ""
    elif staleness_status == "stale":
        roles_display = f"⚠️ Stale — profile changed since last score"
    else:
        roles_display = html.escape(profile_roles) if profile_roles else ""

    subtitle = f"{roles_display} · {stats_str}" if roles_display else stats_str

    return f'''<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter AI — {date_str}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config = {{ darkMode: 'class' }}</script>
<style>
  .job-card {{ transition: box-shadow 0.1s ease; }}
  .job-card:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .dropdown-panel {{ max-height: 320px; overflow-y: auto; scrollbar-width: thin; }}
  .filter-chip {{ cursor: pointer; user-select: none; }}
</style>
</head>
<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 min-h-screen">

<!-- Header -->
<header class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-50">
  <div class="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
    <div class="min-w-0">
      <h1 class="text-lg font-bold leading-none">🎯 JobHunter AI</h1>
      <p class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">{subtitle}</p>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      <span id="count" class="text-xs text-gray-400 dark:text-gray-500 hidden sm:block"></span>
      <button onclick="toggleDark()" class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-base" title="Toggle dark mode">
        <span id="darkIcon">🌙</span>
      </button>
      <a href="https://github.com/adityamujumdar/job-finder" target="_blank"
         class="text-xs text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300">GitHub ↗</a>
    </div>
  </div>
</header>

<!-- Filters -->
<div class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
  <div class="max-w-5xl mx-auto px-4 py-2 space-y-1.5">

    <!-- Row 1: Search + Priority + New + Sort -->
    <div class="flex flex-wrap gap-1.5 items-center">
      <div class="relative flex-1 min-w-[160px] max-w-xs">
        <input type="text" id="search" placeholder="Search jobs…"
               class="w-full pl-8 pr-3 py-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
               oninput="filterJobs()">
        <svg class="absolute left-2.5 top-2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
      </div>

      <!-- Priority filters -->
      <div class="flex gap-1">
        <button onclick="togglePriority('P1')" id="btn-P1"
                class="filter-chip px-2.5 py-1 rounded text-xs font-semibold bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                title="Apply today — score 85–100">P1 · {p1}</button>
        <button onclick="togglePriority('P2')" id="btn-P2"
                class="filter-chip px-2.5 py-1 rounded text-xs font-semibold bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
                title="Apply this week — score 70–84">P2 · {p2}</button>
        <button onclick="togglePriority('P3')" id="btn-P3"
                class="filter-chip px-2.5 py-1 rounded text-xs font-semibold bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-500"
                title="Apply if time — score 50–69">P3 · {p3}</button>
      </div>

      <button onclick="toggleNew()" id="btn-new"
              class="filter-chip px-2.5 py-1 rounded text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800"
              title="Show only new jobs added since yesterday">★ New{f" · {new_count}" if new_count else ""}</button>

      <select id="sort" onchange="filterJobs()"
              class="px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-xs text-gray-600 dark:text-gray-400 focus:outline-none">
        <option value="score">Score ↓</option>
        <option value="company">Company</option>
        <option value="title">Title</option>
        <option value="date">Newest</option>
      </select>

      <button onclick="resetAllFilters()" id="reset-btn"
              class="hidden text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 ml-auto">
        Clear ✕
      </button>
    </div>

    <!-- Row 2: Dropdowns + active chips -->
    <div class="flex flex-wrap gap-1.5 items-center">

      <!-- Company Dropdown -->
      <div class="relative" id="company-dropdown-wrap">
        <button onclick="toggleDropdown('company')" id="company-dropdown-btn"
                class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600">
          Company
          <span id="company-badge" class="hidden px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 font-bold text-[10px]">0</span>
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="company-panel" class="hidden absolute left-0 top-full mt-1 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-40">
          <div class="p-2 border-b border-gray-100 dark:border-gray-700">
            <input type="text" id="company-search" placeholder="Search companies…"
                   class="w-full px-2.5 py-1.5 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-xs focus:outline-none"
                   oninput="filterCompanyList()">
          </div>
          <div class="px-2 py-1 border-b border-gray-100 dark:border-gray-700 flex gap-1">
            <button onclick="selectAllCompanies()" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400">All</button>
            <button onclick="clearAllCompanies()" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400">None</button>
          </div>
          <div id="company-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- Location Dropdown -->
      <div class="relative" id="location-dropdown-wrap">
        <button onclick="toggleDropdown('location')" id="location-dropdown-btn"
                class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600">
          Location
          <span id="location-badge" class="hidden px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 font-bold text-[10px]">0</span>
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="location-panel" class="hidden absolute left-0 top-full mt-1 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-40">
          <div class="p-2 border-b border-gray-100 dark:border-gray-700">
            <input type="text" id="location-search" placeholder="Search locations…"
                   class="w-full px-2.5 py-1.5 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-xs focus:outline-none"
                   oninput="filterLocationList()">
          </div>
          <div class="px-2 py-1 border-b border-gray-100 dark:border-gray-700 flex gap-1">
            <button onclick="selectAllLocations()" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400">All</button>
            <button onclick="clearAllLocations()" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400">None</button>
          </div>
          <div id="location-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- Platform Dropdown -->
      <div class="relative" id="ats-dropdown-wrap">
        <button onclick="toggleDropdown('ats')" id="ats-dropdown-btn"
                class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600">
          Platform
          <svg class="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div id="ats-panel" class="hidden absolute left-0 top-full mt-1 w-44 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-40">
          <div id="ats-list" class="dropdown-panel p-1"></div>
        </div>
      </div>

      <!-- Active filter chips -->
      <div id="active-filters" class="flex flex-wrap gap-1 items-center"></div>
    </div>
  </div>
</div>

<!-- Job Cards -->
<div class="max-w-5xl mx-auto px-4 py-4 pb-16">
  <div id="jobs" class="space-y-2"></div>
  <div id="empty" class="hidden text-center py-20 text-gray-400 dark:text-gray-600">
    <p class="text-3xl mb-3">🔍</p>
    <p class="font-medium">No jobs match your filters</p>
    <p class="text-sm mt-1">Try clearing some filters</p>
  </div>
  <div id="load-more-container" class="text-center py-6 hidden">
    <button onclick="loadMore()" id="load-more-btn"
            class="px-5 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800">
      Load more
    </button>
  </div>
</div>

<!-- Footer -->
<footer class="border-t border-gray-200 dark:border-gray-700 py-4">
  <div class="max-w-5xl mx-auto px-4 flex flex-wrap justify-between gap-2 text-xs text-gray-400 dark:text-gray-600">
    <span>📋 Sample dashboard — <a href="https://github.com/adityamujumdar/job-finder#get-started-in-3-steps-10-minutes" target="_blank" class="underline hover:text-gray-600">fork the repo</a> to see your own matches</span>
    <span>Data from <a href="https://github.com/Feashliaa/job-board-aggregator" target="_blank" class="underline hover:text-gray-600">job-board-aggregator</a> · <a href="https://github.com/adityamujumdar/job-finder" target="_blank" class="underline hover:text-gray-600">MIT</a></span>
  </div>
</footer>

<script>
// ── Data ──
const ALL_JOBS = {jobs_json};
let filtered = [...ALL_JOBS];
let activePriorities = new Set(["P1", "P2", "P3"]);
// null = no filter (show all); empty Set = show none; non-empty Set = filter to these
let selectedCompanies = null;
let selectedLocations = null;
let selectedATS = new Set();
let newOnly = false;
let PAGE_SIZE = 50;
let shown = 0;

// ── Build filter options ──
const companyMap = {{}};
const locationMap = {{}};
const atsMap = {{}};

ALL_JOBS.forEach(j => {{
  if (j.c) companyMap[j.c] = (companyMap[j.c]||0) + 1;
  if (j.l) {{
    let loc = j.l.includes('Remote') ? 'Remote' : j.l.split(',').slice(0,2).join(',').trim();
    if (loc.length > 40) loc = loc.substring(0, 40);
    locationMap[loc] = (locationMap[loc]||0) + 1;
  }}
  if (j.a) atsMap[j.a] = (atsMap[j.a]||0) + 1;
}});

const companiesSorted = Object.entries(companyMap).sort((a,b) => b[1]-a[1]);
const locationsSorted = Object.entries(locationMap).sort((a,b) => b[1]-a[1]);
const atsSorted = Object.entries(atsMap).sort((a,b) => b[1]-a[1]);

// ── Priority styles ──
const PC = {{
  P1: {{ border: "border-l-2 border-l-red-400",    badge: "text-red-600 dark:text-red-400" }},
  P2: {{ border: "border-l-2 border-l-amber-400",  badge: "text-amber-600 dark:text-amber-400" }},
  P3: {{ border: "border-l-2 border-l-yellow-400", badge: "text-yellow-600 dark:text-yellow-500" }},
}};

// ── Render ──
function esc(s) {{ return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : ''; }}

function renderCard(j) {{
  const pc = PC[j.p] || PC.P3;
  const newDot = j.new ? '<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 mb-0.5" title="New today"></span>' : '';
  const meta = [
    `<span class="font-medium ${{pc.badge}}">${{j.p}}</span>`,
    j.lv ? `<span>${{esc(j.lv)}}</span>` : '',
    j.d  ? `<span>${{j.d}}</span>` : '',
    `<span class="font-mono text-gray-300 dark:text-gray-700 select-all" title="Job ID — tell Claude: build resume for job ${{j.id}}">#${{j.id}}</span>`,
  ].filter(Boolean).join('<span class="mx-1 text-gray-300 dark:text-gray-700">·</span>');

  return `<div class="job-card ${{pc.border}} bg-white dark:bg-gray-800 rounded-lg px-4 py-3">
    <div class="flex items-start justify-between gap-4">
      <div class="flex-1 min-w-0">
        <h3 class="font-semibold text-sm leading-snug" title="${{esc(j.t)}}">${{esc(j.t)}}</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 truncate">
          <span class="hover:text-gray-700 dark:hover:text-gray-200 cursor-pointer" onclick="filterByCompany('${{esc(j.c)}}')">${{esc(j.c)}}</span>
          ${{newDot ? ' ' + newDot : ''}}
          ${{j.l ? '<span class="mx-1 text-gray-300 dark:text-gray-700">·</span><span class="hover:text-gray-700 dark:hover:text-gray-200 cursor-pointer" onclick="filterByLocation(\\'' + esc(j.l) + '\\')">' + esc(j.l) + '</span>' : ''}}
        </p>
        <p class="text-[11px] text-gray-400 dark:text-gray-600 mt-1 flex flex-wrap gap-x-0.5 items-center">${{meta}}</p>
      </div>
      ${{j.u ? `<a href="${{j.u}}" target="_blank" rel="noopener"
           class="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline whitespace-nowrap">
           Apply ↗</a>` : ''}}
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
    countEl.textContent = '';
    return;
  }}

  empty.classList.add('hidden');
  shown = Math.min(PAGE_SIZE, filtered.length);
  container.innerHTML = filtered.slice(0, shown).map(renderCard).join('');

  if (shown < filtered.length) {{
    loadMoreC.classList.remove('hidden');
    document.getElementById('load-more-btn').textContent = `Load more (${{filtered.length - shown}} remaining)`;
  }} else {{ loadMoreC.classList.add('hidden'); }}

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
  else {{ document.getElementById('load-more-btn').textContent = `Load more (${{filtered.length - shown}} remaining)`; }}
}}

// ── Filtering ──
function filterJobs() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  const sort = document.getElementById('sort').value;

  filtered = ALL_JOBS.filter(j => {{
    if (!activePriorities.has(j.p)) return false;
    if (newOnly && !j.new) return false;
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
    case 'score':   filtered.sort((a,b) => b.s - a.s); break;
    case 'company': filtered.sort((a,b) => a.c.localeCompare(b.c)); break;
    case 'title':   filtered.sort((a,b) => a.t.localeCompare(b.t)); break;
    case 'date':    filtered.sort((a,b) => b.d.localeCompare(a.d)); break;
  }}

  renderJobs();
  updateActiveFilters();
  updateResetBtn();
}}

// ── Priority toggles ──
function togglePriority(p) {{
  const btn = document.getElementById('btn-' + p);
  if (activePriorities.has(p)) {{ activePriorities.delete(p); btn.style.opacity = '0.35'; }}
  else {{ activePriorities.add(p); btn.style.opacity = '1'; }}
  filterJobs();
}}

function toggleNew() {{
  newOnly = !newOnly;
  document.getElementById('btn-new').style.opacity = newOnly ? '1' : '0.45';
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
    const checked = selectedCompanies === null || selectedCompanies.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleCompany('${{esc(name)}}')" class="rounded text-blue-600 accent-blue-600">
      <span class="flex-1 truncate">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('') + (items.length > 200 ? `<p class="text-[10px] text-gray-400 px-2 py-1">Showing 200 of ${{items.length}} — search to narrow</p>` : '');
}}

function filterCompanyList() {{ buildCompanyList(document.getElementById('company-search').value); }}

function toggleCompany(name) {{
  if (selectedCompanies === null) {{ selectedCompanies = new Set([name]); }}
  else if (selectedCompanies.has(name)) {{ selectedCompanies.delete(name); }}
  else {{ selectedCompanies.add(name); }}
  updateCompanyBadge(); buildCompanyList(); filterJobs();
}}

function filterByCompany(name) {{
  selectedCompanies = new Set([name]);
  updateCompanyBadge(); buildCompanyList(); filterJobs();
}}

function selectAllCompanies() {{ selectedCompanies = null; updateCompanyBadge(); buildCompanyList(); filterJobs(); }}
function clearAllCompanies() {{ selectedCompanies = new Set(); updateCompanyBadge(); buildCompanyList(); filterJobs(); }}

function updateCompanyBadge() {{
  const badge = document.getElementById('company-badge');
  if (selectedCompanies !== null && selectedCompanies.size > 0) {{
    badge.textContent = selectedCompanies.size; badge.classList.remove('hidden');
  }} else {{ badge.classList.add('hidden'); }}
}}

// ── Location dropdown ──
function buildLocationList(filter = '') {{
  const list = document.getElementById('location-list');
  const fl = filter.toLowerCase();
  const items = locationsSorted.filter(([name]) => !fl || name.toLowerCase().includes(fl));
  list.innerHTML = items.slice(0, 150).map(([name, count]) => {{
    const checked = selectedLocations === null || selectedLocations.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleLocation('${{esc(name)}}')" class="rounded text-blue-600 accent-blue-600">
      <span class="flex-1 truncate">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('');
}}

function filterLocationList() {{ buildLocationList(document.getElementById('location-search').value); }}

function toggleLocation(name) {{
  if (selectedLocations === null) {{ selectedLocations = new Set([name]); }}
  else if (selectedLocations.has(name)) {{ selectedLocations.delete(name); }}
  else {{ selectedLocations.add(name); }}
  updateLocationBadge(); buildLocationList(); filterJobs();
}}

function filterByLocation(name) {{
  let loc = name.includes('Remote') ? 'Remote' : name.split(',').slice(0,2).join(',').trim();
  if (loc.length > 40) loc = loc.substring(0, 40);
  selectedLocations = new Set([loc]);
  updateLocationBadge(); buildLocationList(); filterJobs();
}}

function selectAllLocations() {{ selectedLocations = null; updateLocationBadge(); buildLocationList(); filterJobs(); }}
function clearAllLocations() {{ selectedLocations = new Set(); updateLocationBadge(); buildLocationList(); filterJobs(); }}

function updateLocationBadge() {{
  const badge = document.getElementById('location-badge');
  if (selectedLocations !== null && selectedLocations.size > 0) {{
    badge.textContent = selectedLocations.size; badge.classList.remove('hidden');
  }} else {{ badge.classList.add('hidden'); }}
}}

// ── ATS dropdown ──
function buildATSList() {{
  const list = document.getElementById('ats-list');
  list.innerHTML = atsSorted.map(([name, count]) => {{
    const checked = selectedATS.size === 0 || selectedATS.has(name);
    return `<label class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer text-xs">
      <input type="checkbox" ${{checked ? 'checked' : ''}} onchange="toggleATS('${{esc(name)}}')" class="rounded accent-blue-600">
      <span class="flex-1 uppercase text-gray-600 dark:text-gray-400">${{esc(name)}}</span>
      <span class="text-gray-400 text-[10px]">${{count}}</span>
    </label>`;
  }}).join('');
}}

function toggleATS(name) {{
  if (selectedATS.has(name)) {{ selectedATS.delete(name); }}
  else {{ selectedATS.add(name); }}
  filterJobs();
}}

// ── Active filter chips ──
function updateActiveFilters() {{
  const container = document.getElementById('active-filters');
  let chips = [];
  if (selectedCompanies !== null) {{
    selectedCompanies.forEach(c => {{
      chips.push(`<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
        ${{esc(c)}} <button onclick="selectedCompanies.delete('${{esc(c)}}'); updateCompanyBadge(); buildCompanyList(); filterJobs();" class="hover:text-red-500">✕</button></span>`);
    }});
  }}
  if (selectedLocations !== null) {{
    selectedLocations.forEach(l => {{
      chips.push(`<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
        ${{esc(l)}} <button onclick="selectedLocations.delete('${{esc(l)}}'); updateLocationBadge(); buildLocationList(); filterJobs();" class="hover:text-red-500">✕</button></span>`);
    }});
  }}
  container.innerHTML = chips.join('');
}}

function updateResetBtn() {{
  const hasFilters = selectedCompanies !== null || selectedLocations !== null || selectedATS.size > 0 || newOnly;
  document.getElementById('reset-btn').classList.toggle('hidden', !hasFilters);
}}

function resetAllFilters() {{
  selectedCompanies = null; selectedLocations = null; selectedATS.clear();
  newOnly = false;
  activePriorities = new Set(["P1","P2","P3"]);
  document.getElementById('search').value = '';
  document.getElementById('btn-new').style.opacity = '0.45';
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

if (localStorage.getItem('dark') === 'true' ||
    (!localStorage.getItem('dark') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {{
  document.documentElement.classList.add('dark');
  document.getElementById('darkIcon').textContent = '☀️';
}}

// ── Init ──
document.getElementById('btn-new').style.opacity = '0.45';
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
