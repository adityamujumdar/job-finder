#!/bin/bash
# Check for upstream changes to JBA fetcher code.
# Compares pinned SHA in src/jba_fetcher.py against latest JBA commit.

set -euo pipefail

REPO="Feashliaa/job-board-aggregator"
PINNED_SHA=$(grep "Pinned SHA:" src/jba_fetcher.py | sed 's/.*Pinned SHA: //' | head -1)

echo "Pinned SHA: $PINNED_SHA"

LATEST_SHA=$(curl -s "https://api.github.com/repos/$REPO/commits/main" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")
echo "Latest SHA: $LATEST_SHA"

if [ "$PINNED_SHA" = "$LATEST_SHA" ]; then
    echo "✅ Vendored code is up to date."
    exit 0
fi

echo "⚠️  Upstream has changed!"
echo ""
echo "Diff (scraper.py only):"
echo "========================"

# Clone to temp, diff the relevant functions
TMP=$(mktemp -d)
cd "$TMP"
curl -sL "https://raw.githubusercontent.com/$REPO/$LATEST_SHA/scripts/scraper.py" > upstream_scraper.py
echo "Downloaded upstream scraper.py"
echo ""
echo "Key function changes:"
for func in fetch_company_jobs_greenhouse fetch_company_jobs_ashby fetch_company_jobs_bamboohr fetch_company_jobs_lever fetch_company_jobs_workday fetch_company_jobs_workable job_tier_classification is_recruiter_company clean_job_data; do
    if grep -q "def $func" upstream_scraper.py 2>/dev/null; then
        echo "  ✓ $func exists upstream"
    else
        echo "  ✗ $func MISSING upstream (renamed or removed?)"
    fi
done
rm -rf "$TMP"

echo ""
echo "To update: manually review changes and update src/jba_fetcher.py"
echo "Then update Pinned SHA to: $LATEST_SHA"
