"""
Crawls a documentation site into local JSON files, one per page.

Deliberately does NOT touch Qdrant — crawling and ingestion are separate steps so
you can inspect the extracted text by hand before embedding anything. Ingestion
(app/ingestion/processor.py) reads the JSON this produces.

Runs on the dev machine only, never inside the deployed container.

Usage:
    python -m app.ingestion.crawler cp-algorithms https://cp-algorithms.com/sitemap.xml --limit 5
    python -m app.ingestion.crawler cp-algorithms https://cp-algorithms.com/sitemap.xml
"""
# --- Imports: standard library ---
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

# --- Imports: third-party ---
import logfire
import trafilatura


# --- Config ---
# Identify the bot honestly. Some sites block unknown/absent user agents, and a
# real contact string is the polite convention if an operator wants to reach you.
USER_AGENT = "WebsiteOS-Bot/0.1 (documentation indexer)"

# Seconds to wait between page fetches. Without this you can be rate-limited or
# IP-banned — 170 requests as fast as Python can issue them looks like an attack.
CRAWL_DELAY = 0.7

REQUEST_TIMEOUT = 25

# Where crawled JSON lands: crawled_data/<site_name>/<slug>.json
OUTPUT_ROOT = "crawled_data"

# Sitemap URLs whose last path segment matches these are site scaffolding, not
# content. Ingesting them adds noise that competes with real answers in retrieval.
# 'tags' is an auto-generated tag index — a page of links, not documentation. It
# passes every other check (4,944 chars extracted, well above the size floor), so
# only reading a sample by hand surfaced it as low-value for retrieval.
SKIP_PAGES = {"index", "code_of_conduct", "contrib", "navigation", "preview", "404", "tags"}

# Sitemap XML namespace — ElementTree requires the namespace to find <loc> tags.
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# --- Sitemap ---
def fetch_sitemap_urls(sitemap_url: str) -> list[str]:
    """
    Download a sitemap and return every page URL listed in it.

    Handles both shapes a sitemap can take:
      - <urlset>     — a flat list of pages (cp-algorithms uses this: 170 URLs)
      - <sitemapindex> — a list of OTHER sitemaps, each needing its own fetch
    """

    # STEP 1: Fetch the sitemap URL. Build a urllib Request with the USER_AGENT
    #         header, open it with REQUEST_TIMEOUT, read the bytes.
    request = urllib.request.Request(sitemap_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()

    # STEP 2: Parse the bytes with ET.fromstring(...) to get the root element.
    root = ET.fromstring(raw)

    # STEP 3: Check what kind of sitemap this is. root.tag looks like
    #         '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset' — the namespace
    #         is wrapped in braces, so split on '}' and take the last part.

    #       — '{...schemas/sitemap/0.9}urlset' -> 'urlset'
    tag = root.tag.split("}")[-1]

    # Every <loc> under the root, whatever kind of sitemap this turns out to be.
    locs = [loc.text.strip() for loc in root.findall(".//s:loc", SITEMAP_NS) if loc.text]

    # STEP 4: If the root tag is 'sitemapindex', this file points at other sitemaps.
    #         Find every <loc>, and for each one call THIS function again
    #         (recursion), collecting all results into one list. Then return it.
    #        — these <loc>s point at OTHER sitemaps, so recurse into each one.
    if tag == "sitemapindex":
        urls: list[str] = []
        for child_sitemap in locs:
            urls.extend(fetch_sitemap_urls(child_sitemap))
    # STEP 5: Otherwise it's a 'urlset' — find every <loc> element using
    #         root.findall('.//s:loc', SITEMAP_NS) and return their .text values.
    #         — a flat <urlset>: the <loc>s are already page URLs.
    else:
        urls = locs

    # STEP 6: Log how many URLs were found (logfire.info) so a silent empty
    #         result is obvious rather than mysterious.
    logfire.info(f"Found {len(urls)} URLs in sitemap {sitemap_url}")
    return urls


def should_skip(url: str) -> bool:
    """
    True if this URL is site scaffolding rather than documentation content.

    Checked before fetching, so skipped pages cost no request at all.
    """
    # STEP 1: Take the last path segment of the URL (everything after the final '/').
    #         rstrip('/') first so a trailing slash doesn't leave an empty segment:
    #         'https://site.com/contrib/' -> 'contrib', not ''.
    last_segment = url.rstrip("/").split("/")[-1]

    # STEP 2: Strip a trailing '.html' extension if present, so 'contrib.html'
    #         becomes 'contrib'.
    name = last_segment.removesuffix(".html")

    # STEP 3: Return True if that name is in SKIP_PAGES.
    return name in SKIP_PAGES


# --- Fetching ---
def fetch_page(url: str) -> str | None:
    """
    Download one page's raw HTML.

    Returns None instead of raising on any failure. One unreachable page out of
    170 should not abort the whole crawl — the caller skips it and continues.
    """
    
    # request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    # STEP 2: Open it inside a try/except with REQUEST_TIMEOUT.
    try:
        # STEP 1: Build a urllib Request with the USER_AGENT header.
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()

        # STEP 3: Read the response bytes and decode to str. Use
        #         .decode('utf-8', 'replace') — 'replace' substitutes a placeholder for
        #         any malformed byte instead of raising, which would kill the crawl over
        #         one bad character.
        return raw.decode("utf-8", "replace")

    # STEP 4: On any exception, logfire.warning with the url and the error, then
    #         return None. Broad `Exception` is deliberate: timeouts, DNS failures,
    #         HTTP errors and malformed responses all mean the same thing here —
    #         skip this page, keep crawling.
    except Exception as e:
        logfire.warning(f"Failed to fetch {url}: {e}")
        return None


# --- Extraction ---
def extract_headings(html: str) -> list[dict]:
    """
    Pull each section heading and its REAL anchor id straight from the HTML.

    Why read the id instead of computing it: MkDocs generates ids by rules we'd
    have to guess at. Measured on cp-algorithms, it deletes '$' and ':' —
    'Applying a permutation $k$ times' becomes id 'applying-a-permutation-k-times'.
    A slugified guess produces 'applying-a-permutation-$k$-times', which matches no
    element, so the browser silently scrolls to the top. That's a broken citation
    that looks like a working one. The id is already in the HTML; just read it.

    Returns: [{"text": "Algorithm", "id": "algorithm"}, ...]
    """
    # STEP 1: Find every <h1>/<h2>/<h3> tag that has an id attribute. A regex over
    #         the raw HTML is enough here:
    #           <(h[1-3])[^>]*id="([^"]+)"[^>]*>(.*?)</\1>
    #         Use re.S so '.' also matches newlines (headings can wrap lines).
    #         The \1 backreference closes on the SAME tag that opened, so an <h2>
    #         can't accidentally match a later </h3>.
    pattern = r'<(h[1-3])[^>]*id="([^"]+)"[^>]*>(.*?)</\1>'
    matches = re.findall(pattern, html, re.S)

    headings: list[dict] = []

    # STEP 2: For each match, capture the tag level, the id, and the inner HTML.
    #         The level (h1/h2/h3) isn't used yet — the leading underscore says
    #         "ignored on purpose" and keeps linters quiet.
    for _level, heading_id, inner in matches:

        # STEP 3: The inner HTML contains nested tags (MkDocs wraps the permalink in an
        #         <a>). Strip all tags with re.sub(r'<[^>]+>', '', inner).
        text = re.sub(r"<[^>]+>", "", inner)

        # STEP 4: Remove the pilcrow. It appears BOTH as the literal character '¶' and
        #         as the HTML entity '&para;' — handle both, then .strip().
        text = text.replace("¶", "").replace("&para;", "").strip()

        # STEP 5: Skip any heading whose text is empty after cleaning. A heading that
        #         held nothing but the permalink anchor cleans down to '' — useless as
        #         a citation label.
        if not text:
            continue

        headings.append({"text": text, "id": heading_id})

    # STEP 6: Return the list of {"text": ..., "id": ...} dicts.
    return headings


def clean_title(raw_title: str) -> str:
    """Strip the trailing pilcrow MkDocs appends to every heading."""
    # STEP 1: Remove '¶' and '&para;' anywhere in the string. Both forms show up:
    #         the raw HTML carries the '&para;' entity, but anything that has already
    #         been through an HTML-to-text step carries the decoded '¶'.
    title = raw_title.replace("¶", "").replace("&para;", "")

    # STEP 2: .strip() whitespace and return.
    return title.strip()


def unwrap_display_math(html: str) -> str:
    """
    Rewrite <div class="arithmatex">$$..$$</div> as a <p> so trafilatura keeps it.

    Why this exists: MkDocs puts DISPLAY formulas in a <div> and INLINE ones in a
    <span>. trafilatura keeps the spans and discards the divs, so every standalone
    equation vanished while the prose around it survived — the worst possible
    failure mode, because the chunk still looks healthy. Measured on 5 pages: 17
    formulas lost, exactly matching the display-<div> count on every page, and
    balanced-ternary.html ended mid-sentence on the words that introduce a formula
    that wasn't there. A <p> carries the same text and trafilatura keeps it.
    """
    return re.sub(r'<div class="arithmatex">(.*?)</div>', r"<p>\1</p>", html, flags=re.S)


def extract_content(html: str, url: str) -> dict | None:
    """
    Turn raw HTML into the record we save for one page.

    Returns None when there's no usable article — nav-only pages, redirects, and
    JS-rendered shells all produce near-empty extractions and should be dropped
    rather than embedded as noise.

    Returns:
        {"url", "title", "text", "headings", "content_hash", "raw_html_chars"}
    """
    # STEP 1: Call trafilatura.extract(html, url=url, output_format="markdown",
    #         include_formatting=True, with_metadata=True).
    #         markdown + include_formatting are REQUIRED, not stylistic: plain text
    #         flattens headings and code blocks, and on this site the C++ code is
    #         the substance (verified: 4 fenced blocks survive, LaTeX intact).
    #         Feed it the math-unwrapped HTML, not the raw HTML — see
    #         unwrap_display_math() for why. `html` itself stays untouched so
    #         raw_html_chars below still measures the real page.
    text = trafilatura.extract(
        unwrap_display_math(html),
        url=url,
        output_format="markdown",
        include_formatting=True,
        with_metadata=False,
    )

    # STEP 2: If the result is None or shorter than ~200 chars, log a warning and
    #         return None — nothing worth ingesting. None means trafilatura found no
    #         article at all; a very short result means it found only nav/boilerplate.
    if text is None or len(text) < 200:
        logfire.warning(f"No usable content extracted from {url} — skipping.")
        return None

    text = text.replace("¶", "")

    # STEP 3: Get the title. trafilatura's metadata header carries one, but the
    #         simplest reliable source is the first '# ' line of the markdown, or
    #         the first extract_headings() entry. Run it through clean_title().
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = clean_title(line[2:])
            break

    # STEP 4: Call extract_headings(html) for the anchors.
    headings = extract_headings(html)

    # Fallback chain for the title: markdown '# ' line -> first heading -> the URL's
    # last path segment. A page always ends up with *some* label for citations.
    if not title and headings:
        title = clean_title(headings[0]["text"])
    if not title:
        title = url.rstrip("/").split("/")[-1]

    # STEP 5: Compute content_hash: sha256 of the extracted TEXT (not the HTML —
    #         HTML changes on every build from timestamps and asset hashes, so
    #         hashing it would mark every page as changed on every re-crawl).
    #         hashlib.sha256(text.encode("utf-8")).hexdigest()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # STEP 6: Return the dict. Include raw_html_chars=len(html) so you can spot
    #         extraction failures later by comparing it against len(text).
    return {
        "url": url,
        "title": title,
        "text": text,
        "headings": headings,
        "content_hash": content_hash,
        "raw_html_chars": len(html),
    }


# --- Orchestration ---
def save_page(page: dict, site_name: str) -> str:
    """Write one page record to crawled_data/<site_name>/<slug>.json."""
    # STEP 1: Build the output folder path from OUTPUT_ROOT and site_name;
    #         os.makedirs(..., exist_ok=True). exist_ok means a re-crawl reuses the
    #         existing folder instead of raising on the second run.
    out_dir = os.path.join(OUTPUT_ROOT, site_name)
    os.makedirs(out_dir, exist_ok=True)

    # STEP 2: Derive a filename from the URL path — replace '/' and '.' with '_'
    #         so 'algebra/binary-exp.html' becomes 'algebra_binary-exp_html'.
    #         Filenames can't contain slashes.
    #         split('://')[-1] drops the scheme, then the first split('/', 1) drops
    #         the hostname, leaving just the site-relative path to flatten.
    path = page["url"].split("://")[-1]
    path = path.split("/", 1)[1] if "/" in path else path
    slug = path.strip("/").replace("/", "_").replace(".", "_")

    #         The site root ('https://cp-algorithms.com/') has no path at all and
    #         flattens to an empty slug — which would write a bare '.json'. Name it
    #         'index' instead. should_skip() doesn't catch this URL, so it does occur.
    slug = slug or "index"

    # STEP 3: json.dump the page dict with ensure_ascii=False (keeps LaTeX and
    #         unicode readable when you inspect the file) and indent=2.
    #         encoding='utf-8' is explicit because Windows would otherwise write
    #         cp1252 and choke on the first non-ASCII character.
    file_path = os.path.join(out_dir, f"{slug}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(page, f, ensure_ascii=False, indent=2)

    # STEP 4: Return the path written.
    return file_path


def crawl_site(site_name: str, sitemap_url: str, limit: int | None = None) -> int:
    """
    Crawl one site end to end: sitemap -> fetch -> extract -> save.

    Returns the number of pages successfully saved.

    Always run with a small `limit` first and READ the output JSON by hand before
    crawling everything. Extraction quality is site-specific — if it's wrong,
    every downstream step (chunking, embedding, retrieval, citations) inherits it.
    """
    # STEP 1: Open a logfire.span for the whole crawl (site_name, sitemap_url).
    with logfire.span("Crawling Site", site_name=site_name, sitemap_url=sitemap_url):

        # STEP 2: fetch_sitemap_urls(sitemap_url) -> all URLs.
        all_urls = fetch_sitemap_urls(sitemap_url)

        # STEP 3: Filter out should_skip(url) entries. Done before any fetching, so
        #         scaffolding pages cost zero requests.
        urls = [u for u in all_urls if not should_skip(u)]
        logfire.info(f"{len(urls)} URLs to crawl ({len(all_urls) - len(urls)} skipped).")

        # STEP 4: If limit is not None, truncate the list to that many URLs.
        if limit is not None:
            urls = urls[:limit]
            logfire.info(f"Limit applied — crawling {len(urls)} URLs.")

        # STEP 5: Loop the URLs, tracking a saved counter.
        saved = 0
        for i, url in enumerate(urls, start=1):

            #   a. fetch_page(url); if None, continue.
            html = fetch_page(url)

            #   d. time.sleep(CRAWL_DELAY) <- unconditional, inside the loop.
            #      Placed here rather than at the end of the body on purpose: the
            #      `continue`s below would jump over a sleep placed after them, and a
            #      failed fetch still hit the server, so it still owes the delay.
            time.sleep(CRAWL_DELAY)

            if html is None:
                continue

            #   b. extract_content(html, url); if None, continue.
            page = extract_content(html, url)
            if page is None:
                continue

            #   c. save_page(page, site_name); increment saved.
            save_page(page, site_name)
            saved += 1

            #   e. log progress every N pages so a long crawl isn't silent.
            if i % 10 == 0:
                logfire.info(f"Progress: {i}/{len(urls)} URLs processed, {saved} saved.")

        # STEP 6: Log and return the saved count.
        logfire.info(f"Crawl finished for '{site_name}': {saved}/{len(urls)} pages saved.")
        return saved


# --- CLI entry point ---
if __name__ == "__main__":
    # NOTE: sys.stdout.reconfigure(encoding="utf-8") first — Windows consoles
    #       default to cp1252 and will crash printing LaTeX or unicode titles.
    sys.stdout.reconfigure(encoding="utf-8")

    # STEP 1: Read sys.argv — expect: <site_name> <sitemap_url> [--limit N]
    #         Pull '--limit N' out into its own pair first, the way processor.py
    #         strips '--wipe', so the positional args stay at fixed indexes no
    #         matter where the flag was typed.
    args = sys.argv[1:]
    if "--limit" in args:
        i = args.index("--limit")
        limit_raw = args[i + 1] if i + 1 < len(args) else None
        positional = args[:i] + args[i + 2:]
    else:
        limit_raw = None
        positional = args

    # STEP 2: If the required args are missing, print the usage line from the
    #         module docstring and sys.exit(1).
    if len(positional) < 2:
        print(__doc__)
        sys.exit(1)

    site_name, sitemap_url = positional[0], positional[1]

    # STEP 3: Parse an optional --limit N into an int (None if absent). Exit on a
    #         non-integer rather than silently crawling all 170 pages — the whole
    #         point of --limit is to NOT do that by accident.
    limit = None
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            print(f"--limit needs an integer, got: {limit_raw!r}")
            sys.exit(1)
    elif "--limit" in args:
        print("--limit needs a number after it, e.g. --limit 5")
        sys.exit(1)

    # STEP 4: logfire.configure(service_name="websiteos-crawler") — matches how
    #         processor.py configures itself as a standalone script.
    logfire.configure(service_name="websiteos-crawler")

    # STEP 5: Call crawl_site(...) and print the resulting page count.
    count = crawl_site(site_name, sitemap_url, limit)
    print(f"Saved {count} pages to {OUTPUT_ROOT}/{site_name}/")
