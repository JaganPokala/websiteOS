"""
Render crawled JSON as real .md files so you can READ what was extracted.

The `text` field is markdown, but it lives inside a JSON string — every newline is
stored as the two characters \\n, so the whole page shows up as one unreadable line.
This writes it back out as .md, where VS Code's preview (Ctrl+Shift+V) renders the
headings, fenced code and LaTeX properly.

crawl_site()'s docstring says to read the output by hand before crawling everything.
This is the tool that makes that practical.

Output lands in crawled_data/<site>/_preview/ — a subfolder, so it never collides
with the *.json glob that check_crawl.py and the ingestion step use.

Usage:
    python -m app.ingestion.preview_crawl cp-algorithms          # every page
    python -m app.ingestion.preview_crawl cp-algorithms binary   # only matching names
"""
# --- Imports: standard library ---
import glob
import json
import os
import sys

# --- Config ---
PREVIEW_DIR = "_preview"


def render(record: dict) -> str:
    """One page as readable markdown, with a header block for the citation metadata."""
    # The anchors don't appear in `text`, but they're what citations deep-link with —
    # worth seeing next to the content they point at.
    anchors = "\n".join(f"- `#{h['id']}` — {h['text']}" for h in record["headings"])

    return (
        f"<!-- {record['url']} -->\n"
        f"<!-- {len(record['text'])} chars extracted from "
        f"{record['raw_html_chars']} chars of HTML -->\n\n"
        f"> **Anchors ({len(record['headings'])})**\n>\n"
        + "\n".join(f"> {line}" for line in anchors.splitlines())
        + "\n\n---\n\n"
        + record["text"]
    )


def preview_site(site_name: str, name_filter: str | None = None) -> int:
    """Write a .md next to every crawled .json. Returns how many were written."""
    src_dir = os.path.join("crawled_data", site_name)
    files = sorted(glob.glob(os.path.join(src_dir, "*.json")))

    if name_filter:
        files = [f for f in files if name_filter in os.path.basename(f)]

    if not files:
        where = f"{src_dir}/*.json" + (f" matching {name_filter!r}" if name_filter else "")
        print(f"No files found at {where}")
        return 0

    out_dir = os.path.join(src_dir, PREVIEW_DIR)
    os.makedirs(out_dir, exist_ok=True)

    for path in files:
        record = json.load(open(path, encoding="utf-8"))
        out_path = os.path.join(out_dir, os.path.basename(path).replace(".json", ".md"))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(render(record))
        print(f"  {out_path}")

    print(f"\n{len(files)} file(s) written. Open one and press Ctrl+Shift+V to render it.")
    return len(files)


# --- CLI entry point ---
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    preview_site(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
