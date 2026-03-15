"""Scraper orchestrator — download JBA data + live scrape preferred companies + merge.

Pipeline: download → live scrape → merge (live wins) → dedup → clean → prune stale → save.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone

from src.config import (
    load_profile, today, ensure_dirs,
    JOBS_DIR, SEED_DIR, STALE_DAYS, JBA_REPO,
)
from src.downloader import download_jba_data
from src.jba_fetcher import (
    fetch_company_jobs, clean_job_data,
    get_dedup_key, get_composite_key,
    PLATFORM_FETCHERS,
)

log = logging.getLogger(__name__)


def load_seed_data() -> dict[str, list[str]]:
    """Load seed company slugs per platform from data/seed/."""
    seed = {}
    for platform in PLATFORM_FETCHERS:
        path = SEED_DIR / f"{platform}.json"
        if path.exists():
            with open(path) as f:
                seed[platform] = json.load(f)
    return seed


def scrape_preferred(profile: dict) -> tuple[list[dict], dict]:
    """Live-scrape only preferred companies from profile.

    Returns:
        (jobs, scrape_report) where scrape_report = {
            "succeeded": [{"slug": ..., "platform": ..., "count": ...}],
            "failed": [{"slug": ..., "platform": ..., "error": ...}],
            "total_jobs": int,
            "elapsed_seconds": float,
        }
    """
    preferred = profile.get("preferred_companies", {})
    if not preferred:
        log.info("No preferred companies configured — skipping live scrape")
        return [], {"succeeded": [], "failed": [], "total_jobs": 0, "elapsed_seconds": 0}

    all_jobs = []
    succeeded = []
    failed = []
    t0 = time.time()

    for platform, slugs in preferred.items():
        platform_lower = platform.lower()
        if platform_lower not in PLATFORM_FETCHERS:
            log.warning("Unknown platform in preferred_companies: %s", platform)
            for slug in slugs:
                failed.append({"slug": slug, "platform": platform, "error": "unknown platform"})
            continue

        for slug in slugs:
            try:
                _, jobs = fetch_company_jobs(platform_lower, slug)
                if jobs:
                    all_jobs.extend(jobs)
                    succeeded.append({"slug": slug, "platform": platform_lower, "count": len(jobs)})
                    log.info("  %s/%s: %d jobs", platform_lower, slug, len(jobs))
                else:
                    failed.append({"slug": slug, "platform": platform_lower, "error": "no jobs returned"})
                    log.info("  %s/%s: 0 jobs", platform_lower, slug)
            except Exception as e:
                failed.append({"slug": slug, "platform": platform_lower, "error": str(e)})
                log.warning("  %s/%s failed: %s", platform_lower, slug, e)

    elapsed = time.time() - t0
    scrape_report = {
        "succeeded": succeeded,
        "failed": failed,
        "total_jobs": len(all_jobs),
        "elapsed_seconds": round(elapsed, 1),
    }

    log.info("Live scrape: %d jobs from %d companies in %.1fs (%d failed)",
             len(all_jobs), len(succeeded), elapsed, len(failed))

    return all_jobs, scrape_report


def merge_jobs(jba_jobs: list[dict], live_jobs: list[dict]) -> list[dict]:
    """Merge JBA download data with live scrape data.

    Dedup strategy:
      1. Primary: get_dedup_key (URL-based, Workday composite) — from JBA's merge_data.py
      2. Fallback: get_composite_key (ats, slug, job_id) — catches URL-format drift

    Live data always wins on duplicates.
    """
    # Build dedup maps — JBA first, then live overwrites
    by_primary = {}
    by_composite = {}
    overridden = 0

    # Insert JBA data
    for job in jba_jobs:
        pk = get_dedup_key(job)
        if pk:
            by_primary[pk] = job
        ck = get_composite_key(job)
        if ck:
            by_composite[ck] = pk  # Map composite → primary for cross-reference

    jba_count = len(by_primary)

    # Insert live data — live always wins
    for job in live_jobs:
        pk = get_dedup_key(job)
        ck = get_composite_key(job)

        # Check if this job exists via primary key
        if pk and pk in by_primary:
            by_primary[pk] = job  # Override
            overridden += 1
        # Check if it exists via composite key (catches URL-format drift)
        elif ck and ck in by_composite:
            old_pk = by_composite[ck]
            by_primary[old_pk] = job  # Override at old primary key
            overridden += 1
        elif pk:
            by_primary[pk] = job  # New job
        else:
            # No dedup key — just add (rare edge case)
            by_primary[f"_nokey_{id(job)}"] = job

        # Update composite map
        if ck and pk:
            by_composite[ck] = pk

    log.info("Merge: %d JBA + %d live → %d total (%d overridden by live data)",
             jba_count, len(live_jobs), len(by_primary), overridden)

    return list(by_primary.values())


def prune_stale(jobs: list[dict], max_age_days: int = STALE_DAYS) -> list[dict]:
    """Remove jobs older than max_age_days."""
    now = datetime.now(timezone.utc)
    kept = []
    pruned = 0

    for job in jobs:
        scraped = job.get("scraped_at")
        if scraped:
            try:
                scraped_dt = datetime.fromisoformat(scraped.replace("Z", "+00:00"))
                age = (now - scraped_dt).days
                if age > max_age_days:
                    pruned += 1
                    continue
            except (ValueError, TypeError):
                pass  # Keep jobs with unparseable dates
        kept.append(job)

    if pruned:
        log.info("Pruned %d stale jobs (>%d days old)", pruned, max_age_days)

    return kept


def check_vendor_staleness():
    """Check if vendored JBA code is stale (weekly, non-blocking)."""
    import requests
    try:
        r = requests.get(
            f"https://api.github.com/repos/{JBA_REPO}/commits/main",
            timeout=5,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if r.status_code == 200:
            latest_sha = r.json().get("sha", "")[:12]
            from src.jba_fetcher import __doc__ as fetcher_doc
            if fetcher_doc and latest_sha[:12] not in fetcher_doc:
                log.warning("⚠️  JBA vendor may be stale. Run: scripts/update_vendor.sh")
    except Exception:
        pass  # Non-blocking — don't fail the pipeline for this


def run_pipeline(
    skip_download: bool = False,
    skip_live: bool = False,
    live_only: bool = False,
    force_download: bool = False,
) -> dict:
    """Run the full scraper pipeline.

    Returns:
        Pipeline result dict with job counts, scrape report, and output path.
    """
    ensure_dirs()
    date_str = today()
    output_path = JOBS_DIR / f"{date_str}.json"
    profile = load_profile()

    log.info("=" * 60)
    log.info("SCRAPER PIPELINE — %s", date_str)
    log.info("=" * 60)

    t0 = time.time()

    # ── Step 1: Download JBA data ──────────────────────────────────────────
    jba_jobs = []
    if not skip_download and not live_only:
        log.info("\n[1/4] Downloading JBA data...")
        jba_jobs = download_jba_data(force=force_download)
        log.info("Downloaded %d JBA jobs", len(jba_jobs))
    else:
        log.info("\n[1/4] Skipping JBA download")

    # ── Step 2: Live scrape preferred companies ────────────────────────────
    live_jobs = []
    scrape_report = {"succeeded": [], "failed": [], "total_jobs": 0, "elapsed_seconds": 0}
    if not skip_live:
        log.info("\n[2/4] Live scraping preferred companies...")
        live_jobs, scrape_report = scrape_preferred(profile)
    else:
        log.info("\n[2/4] Skipping live scrape")

    # ── Step 3: Merge + dedup + clean + prune ──────────────────────────────
    log.info("\n[3/4] Merging and cleaning...")
    merged = merge_jobs(jba_jobs, live_jobs)
    cleaned = clean_job_data(merged)
    final = prune_stale(cleaned)

    # ── Step 4: Save ──────────────────────────────────────────────────────
    log.info("\n[4/4] Saving %d jobs to %s", len(final), output_path)
    with open(output_path, "w") as f:
        json.dump(final, f)

    elapsed = time.time() - t0

    # Check vendor staleness (non-blocking, weekly)
    check_vendor_staleness()

    result = {
        "date": date_str,
        "output_path": str(output_path),
        "jba_jobs": len(jba_jobs),
        "live_jobs": len(live_jobs),
        "merged": len(merged),
        "cleaned": len(cleaned),
        "final": len(final),
        "scrape_report": scrape_report,
        "elapsed_seconds": round(elapsed, 1),
    }

    log.info("\n" + "=" * 60)
    log.info("PIPELINE COMPLETE in %.1fs", elapsed)
    log.info("  JBA: %d | Live: %d | Merged: %d | Final: %d",
             len(jba_jobs), len(live_jobs), len(merged), len(final))
    log.info("=" * 60)

    return result


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="JobHunter scraper pipeline")
    parser.add_argument("--skip-download", action="store_true", help="Skip JBA download")
    parser.add_argument("--skip-live", action="store_true", help="Skip live scraping")
    parser.add_argument("--live-only", action="store_true", help="Only live scrape (no JBA)")
    parser.add_argument("--force-download", action="store_true", help="Force re-download JBA data")
    args = parser.parse_args()

    result = run_pipeline(
        skip_download=args.skip_download,
        skip_live=args.skip_live,
        live_only=args.live_only,
        force_download=args.force_download,
    )

    print(f"\nResult: {json.dumps(result, indent=2)}")
