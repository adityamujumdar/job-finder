"""Integration test: Playwright browser works on the main thread.

Verifies that Playwright sync API works for sequential context creation,
which is how run_enricher() uses it (browser jobs run sequentially on
the main thread, NOT in the thread pool).

Also verifies that Playwright sync API CANNOT be called from threads,
validating our split-pipeline architecture.

Requires: pip install playwright && playwright install chromium
Skip: Automatically skipped if Playwright is not installed.
Run:  python3 -m pytest tests/integration/ -q
"""

from __future__ import annotations

import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed


try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
class TestPlaywrightMainThread:
    """Verify Playwright works sequentially on the main thread."""

    def test_sequential_contexts(self):
        """Multiple sequential context creations work on the main thread."""
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)

        results = []
        for i in range(3):
            ctx = browser.new_context()
            try:
                page = ctx.new_page()
                page.goto("data:text/html,<h1>Page %d</h1>" % i)
                text = page.text_content("h1")
                results.append(text or "")
            finally:
                ctx.close()

        browser.close()
        pw.stop()

        assert len(results) == 3
        for r in results:
            assert "Page" in r

    def test_cross_thread_raises_error(self):
        """Playwright sync API from a thread pool raises greenlet.error.

        This validates our architecture decision to run browser jobs
        sequentially rather than in the ThreadPoolExecutor.
        """
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)

        def worker():
            ctx = browser.new_context()
            ctx.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            with pytest.raises(Exception, match="Cannot switch to a different thread|greenlet"):
                future.result(timeout=10)

        browser.close()
        pw.stop()
