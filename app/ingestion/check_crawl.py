"""
Structural quality check over crawled JSON, before any of it reaches Qdrant.

Extraction failures are quiet. A page whose formulas were dropped still has fluent
prose, a sensible title and a healthy character count — it looks fine in the file
and only shows up as a confidently wrong answer weeks later. This script tests the
properties that are cheap to verify now and expensive to discover then.

Run it after every crawl, before ingestion:
    python -m app.ingestion.check_crawl cp-algorithms
"""
# --- Imports: standard library ---
import glob
import json
import os
import re
import sys

# --- Config ---
# Nav/chrome strings. If these reach the extracted text, boilerplate is being
# embedded alongside real content and will compete with it during retrieval.
NAV_MARKERS = ("Skip to content", "Back to top", "Edit this page", "Table of contents")

# Extracted text below this fraction of the raw HTML usually means extraction
# collapsed and kept only a fragment. Tuned on cp-algorithms, where healthy pages
# land at 2-7% (the HTML carries a large embedded nav on every page).
MIN_RATIO = 0.02

# A real documentation page is longer than this. Below it, something went wrong.
MIN_CHARS = 400


def check_page(record: dict, name: str) -> list[str]:
    """Return a list of problem descriptions for one crawled page — empty if clean."""
    problems = []
    text = record["text"]

    # An odd number of fences means a code block was left open. Everything after it
    # chunks as if it were code, or as if it weren't — either way the boundary is wrong.
    if text.count("```") % 2:
        problems.append(f"odd number of ``` ({text.count('```')}) — unterminated code block")

    ratio = len(text) / record["raw_html_chars"]
    if ratio < MIN_RATIO:
        problems.append(f"extraction ratio {ratio:.1%} — likely lost most of the page")

    if len(text) < MIN_CHARS:
        problems.append(f"only {len(text)} chars — suspiciously short")

    # Citations deep-link via these ids. No anchors means no way to point a user at
    # the exact section an answer came from.
    anchors = record["headings"]
    if not anchors:
        problems.append("no heading anchors — citations cannot deep-link")
    if any(not h.get("id") or not h.get("text") for h in anchors):
        problems.append("a heading has an empty id or text")

    # Every heading in the markdown should have a matching anchor id. A mismatch
    # means a citation would point at an element that doesn't exist, and the browser
    # silently scrolls to the top — a broken link that looks like a working one.
    anchor_texts = {h["text"].strip() for h in anchors}
    orphans = [h.strip() for h in re.findall(r"^#{1,3} (.+)$", text, re.M)
               if h.strip() not in anchor_texts]
    if orphans:
        problems.append(f"{len(orphans)} heading(s) with no anchor id: {orphans[:3]}")

    # A page whose prose ends where a formula should start (see unwrap_display_math
    # in crawler.py). Cheap proxy: text ending on a colon.
    if text.rstrip().endswith(":"):
        problems.append("text ends on ':' — content after it was probably dropped")

    for marker in NAV_MARKERS:
        if marker in text:
            problems.append(f"nav text leaked into content: {marker!r}")

    return problems


def check_site(site_name: str) -> int:
    """Check every crawled page for one site. Returns the number of pages with problems."""
    pattern = os.path.join("crawled_data", site_name, "*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No files found at {pattern}")
        return 0

    print(f"{len(files)} files in {os.path.dirname(pattern)}\n")
    header = f"{'file':<40}{'html':>8}{'text':>8}{'ratio':>7}{'code':>6}{'math':>6}{'anchors':>9}"
    print(header)
    print("-" * len(header))

    flagged = {}
    for path in files:
        record = json.load(open(path, encoding="utf-8"))
        name = os.path.basename(path)
        text = record["text"]

        # Inline $..$ plus display $$..$$ — the display count is what regressed before.
        math = len(re.findall(r"\$\$.+?\$\$", text, re.S)) + \
               len(re.findall(r"(?<!\$)\$[^$\n]+\$(?!\$)", text))

        print(f"{name:<40}{record['raw_html_chars']:>8}{len(text):>8}"
              f"{len(text) / record['raw_html_chars']:>7.1%}"
              f"{text.count('```') // 2:>6}{math:>6}{len(record['headings']):>9}")

        problems = check_page(record, name)
        if problems:
            flagged[name] = problems

    print("\n=== FINDINGS ===")
    if not flagged:
        print("none — all pages passed")
    else:
        for name, problems in flagged.items():
            print(f"\n{name}")
            for p in problems:
                print(f"   - {p}")

    print(f"\n{len(files) - len(flagged)}/{len(files)} pages clean.")
    return len(flagged)


# --- CLI entry point ---
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Exit non-zero when anything is flagged, so this can gate ingestion in a script.
    sys.exit(1 if check_site(sys.argv[1]) else 0)
