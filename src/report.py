"""Report generator — CSV output + terminal summary for Claude to present.

Reads scored jobs, generates prioritized CSV and a human-readable summary.
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from src.config import load_profile, today, ensure_dirs, SCORED_DIR, REPORTS_DIR

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "priority", "score", "title", "company", "location", "url",
    "ats", "skill_level", "scraped_at",
]


def generate_report(date: str | None = None, top_n: int = 20) -> dict:
    """Generate CSV report and terminal summary.

    Args:
        date: Date string (YYYY-MM-DD). Defaults to today.
        top_n: Number of top jobs to show in summary.

    Returns:
        Report dict with summary and file paths.
    """
    ensure_dirs()
    date_str = date or today()
    input_path = SCORED_DIR / f"{date_str}.json"
    csv_path = REPORTS_DIR / f"{date_str}.csv"

    if not input_path.exists():
        log.error("No scored data for %s at %s", date_str, input_path)
        return {"error": f"No scored data for {date_str}"}

    with open(input_path) as f:
        scored = json.load(f)

    if not scored:
        summary = _empty_summary(date_str)
        _write_csv(csv_path, [])
        return {"summary": summary, "csv_path": str(csv_path), "total": 0}

    # Already sorted by score desc from matcher
    # Generate CSV
    _write_csv(csv_path, scored)

    # Build summary
    summary = _build_summary(scored, date_str, top_n)

    # Stats
    tier_counts = Counter(j.get("_priority", "P4") for j in scored)
    ats_counts = Counter(j.get("ats", "unknown") for j in scored)
    location_counts = Counter()
    for j in scored:
        loc = (j.get("location") or "Unknown")
        # Simplify: just city/state or "Remote"
        if "remote" in loc.lower():
            location_counts["Remote"] += 1
        else:
            location_counts[loc[:30]] += 1

    result = {
        "date": date_str,
        "total": len(scored),
        "tiers": dict(tier_counts),
        "top_ats": dict(ats_counts.most_common(5)),
        "top_locations": dict(location_counts.most_common(10)),
        "csv_path": str(csv_path),
        "summary": summary,
    }

    # Print summary to stdout (for Claude to read)
    print(summary)

    return result


def _write_csv(path: Path, scored: list[dict]):
    """Write scored jobs to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for job in scored:
            row = {
                "priority": job.get("_priority", "P4"),
                "score": job.get("_score", 0),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "url": job.get("url", ""),
                "ats": job.get("ats", ""),
                "skill_level": job.get("skill_level", ""),
                "scraped_at": job.get("scraped_at", ""),
            }
            writer.writerow(row)
    log.info("CSV written: %s (%d rows)", path, len(scored))


def _build_summary(scored: list[dict], date_str: str, top_n: int) -> str:
    """Build terminal summary string."""
    tier_counts = Counter(j.get("_priority", "P4") for j in scored)
    p1_jobs = [j for j in scored if j.get("_priority") == "P1"]
    p2_jobs = [j for j in scored if j.get("_priority") == "P2"]

    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  JOBHUNTER AI — DAILY REPORT — {date_str}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  📊 Scored {len(scored):,} matching jobs")
    lines.append(f"  🔴 P1 (Apply Now):    {tier_counts.get('P1', 0):,}")
    lines.append(f"  🟠 P2 (This Week):    {tier_counts.get('P2', 0):,}")
    lines.append(f"  🟡 P3 (If Time):      {tier_counts.get('P3', 0):,}")
    lines.append(f"  ⚪ P4 (Reference):    {tier_counts.get('P4', 0):,}")
    lines.append("")

    if p1_jobs:
        lines.append(f"  🔥 TOP P1 MATCHES ({min(top_n, len(p1_jobs))} of {len(p1_jobs)}):")
        lines.append("  " + "-" * 66)
        for i, job in enumerate(p1_jobs[:top_n], 1):
            score = job.get("_score", 0)
            title = (job.get("title") or "Untitled")[:45]
            company = (job.get("company") or "Unknown")[:20]
            location = (job.get("location") or "")[:20]
            lines.append(f"  {i:3d}. [{score:5.1f}] {title}")
            lines.append(f"       {company} | {location}")
            lines.append(f"       {job.get('url', '')}")
            lines.append("")
    elif p2_jobs:
        lines.append("  No P1 matches today. Showing top P2:")
        lines.append("  " + "-" * 66)
        for i, job in enumerate(p2_jobs[:top_n], 1):
            score = job.get("_score", 0)
            title = (job.get("title") or "Untitled")[:45]
            company = (job.get("company") or "Unknown")[:20]
            lines.append(f"  {i:3d}. [{score:5.1f}] {title}")
            lines.append(f"       {company} | {job.get('location', '')[:20]}")
            lines.append("")
    else:
        lines.append("  No strong matches today. Review P3/P4 in CSV.")

    # Platform breakdown
    ats_counts = Counter(j.get("ats", "unknown") for j in scored)
    lines.append("  📡 By Platform:")
    for ats, count in ats_counts.most_common():
        lines.append(f"     {ats}: {count:,}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


def _empty_summary(date_str: str) -> str:
    """Summary when no jobs matched."""
    return f"""
{'=' * 70}
  JOBHUNTER AI — DAILY REPORT — {date_str}
{'=' * 70}

  No matching jobs found. Check:
  - Is job data available? (run scraper first)
  - Are profile settings too restrictive?
  - Is min-score threshold too high?

{'=' * 70}
"""


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="JobHunter report generator")
    parser.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=20, help="Number of top jobs to show")
    args = parser.parse_args()

    result = generate_report(date=args.date, top_n=args.top)
    if "error" not in result:
        log.info("Report saved to %s", result.get("csv_path"))
