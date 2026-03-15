"""Download JBA pre-scraped data from GitHub — 502K+ jobs in ~15 seconds.

Dynamic discovery: fetches manifest first, then downloads listed chunks.
Parallel download with ThreadPoolExecutor. Caches daily.
"""

import gzip
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from src.config import (
    JBA_DIR, JBA_REPO, JBA_BRANCH, JBA_DATA_PATH,
    MIN_JBA_JOBS, DOWNLOAD_WORKERS, today, ensure_dirs,
)

log = logging.getLogger(__name__)

RAW_BASE = f"https://raw.githubusercontent.com/{JBA_REPO}/{JBA_BRANCH}/{JBA_DATA_PATH}"
SESSION = requests.Session()
SESSION.headers.update({"Accept-Encoding": "identity"})  # We handle gzip ourselves


def _download_manifest() -> dict:
    """Fetch jobs_manifest.json from JBA repo."""
    url = f"{RAW_BASE}/jobs_manifest.json"
    log.info("Downloading manifest: %s", url)
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _download_chunk(chunk_name: str) -> list[dict]:
    """Download and decompress a single gzipped JSON chunk.

    Returns list of jobs, or empty list on failure (chunk-level fault tolerance).
    """
    url = f"{RAW_BASE}/{chunk_name}"
    try:
        r = SESSION.get(url, timeout=60)
        r.raise_for_status()
        data = json.loads(gzip.decompress(r.content))
        if not isinstance(data, list):
            log.warning("Chunk %s: expected list, got %s", chunk_name, type(data).__name__)
            return []
        return data
    except (requests.RequestException, gzip.BadGzipFile, json.JSONDecodeError) as e:
        log.warning("Chunk %s failed: %s", chunk_name, e)
        return []


def download_jba_data(force: bool = False) -> list[dict]:
    """Download all JBA job data. Returns list of job dicts.

    Uses daily cache — skips download if today's file exists (unless force=True).
    Falls back to yesterday's cache on failure.

    Args:
        force: Re-download even if cached.

    Returns:
        List of job dicts (500K+).
    """
    ensure_dirs()
    date_str = today()
    cache_path = JBA_DIR / f"{date_str}.json"

    # Check cache
    if not force and cache_path.exists():
        log.info("Using cached JBA data: %s", cache_path)
        with open(cache_path) as f:
            jobs = json.load(f)
        log.info("Loaded %d jobs from cache", len(jobs))
        return jobs

    # Download
    try:
        manifest = _download_manifest()
        chunks = manifest.get("chunks", [])
        total_expected = manifest.get("totalJobs", 0)
        log.info("Manifest: %d chunks, %d expected jobs", len(chunks), total_expected)
    except Exception as e:
        log.error("Manifest download failed: %s", e)
        return _fallback_cache(cache_path)

    # Parallel chunk download
    all_jobs = []
    failed_chunks = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = {pool.submit(_download_chunk, c): c for c in chunks}
        for future in as_completed(futures):
            chunk_name = futures[future]
            try:
                jobs = future.result()
                if jobs:
                    all_jobs.extend(jobs)
                    log.debug("Chunk %s: %d jobs", chunk_name, len(jobs))
                else:
                    failed_chunks.append(chunk_name)
            except Exception as e:
                log.warning("Chunk %s raised: %s", chunk_name, e)
                failed_chunks.append(chunk_name)

    elapsed = time.time() - t0
    log.info("Downloaded %d jobs in %.1fs (%d/%d chunks OK)",
             len(all_jobs), elapsed, len(chunks) - len(failed_chunks), len(chunks))

    if failed_chunks:
        log.warning("Failed chunks: %s", failed_chunks)

    # Validation gate
    if len(all_jobs) < MIN_JBA_JOBS:
        log.error("Validation gate failed: %d jobs < %d minimum", len(all_jobs), MIN_JBA_JOBS)
        return _fallback_cache(cache_path)

    # Save cache
    with open(cache_path, "w") as f:
        json.dump(all_jobs, f)
    log.info("Cached %d jobs to %s", len(all_jobs), cache_path)

    return all_jobs


def _fallback_cache(current_path: Path) -> list[dict]:
    """Try to load yesterday's (or most recent) cached data."""
    cached = sorted(JBA_DIR.glob("*.json"), reverse=True)
    for path in cached:
        if path != current_path:
            log.warning("Falling back to cached data: %s", path)
            with open(path) as f:
                jobs = json.load(f)
            log.info("Loaded %d jobs from fallback cache", len(jobs))
            return jobs
    log.error("No cached data available. Returning empty list.")
    return []


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Download JBA job data")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    args = parser.parse_args()

    jobs = download_jba_data(force=args.force)
    print(f"\n{'='*60}")
    print(f"Downloaded {len(jobs):,} jobs")

    # Quick stats
    ats_counts = {}
    for j in jobs:
        ats = j.get("ats", "unknown")
        ats_counts[ats] = ats_counts.get(ats, 0) + 1
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        print(f"  {ats}: {count:,}")
