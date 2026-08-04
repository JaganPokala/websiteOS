import json
import os
import sys
import uuid

import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.ingestion.chunking.splitter import chunk_text
from app.ingestion.loaders.html import parse_html
from app.ingestion.loaders.office import parse_office
from app.ingestion.loaders.pdf import parse_pdf
from app.ingestion.loaders.text import parse_text
from app.services.retrieval.embedding import embed_texts, get_embedding_dim

logfire.configure(service_name="enterprise-ingestion-service")

qdrant_client = QdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY,
    timeout=120,
)


def ensure_collection(wipe: bool = False):
    """Ensure the Qdrant collection exists, creating it if necessary."""

    # STEP 1: check if collection exists, if not create it
    collection = settings.QDRANT_COLLECTION

    if wipe and qdrant_client.collection_exists(collection):
        logfire.warning("Wiping existing collection", collection=collection)
        qdrant_client.delete_collection(collection)

    # STEP 2: use get_embedding_dim() for the vector size
    if not qdrant_client.collection_exists(collection):
        dim = get_embedding_dim()
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
            ),
        )
        logfire.info("Created collection", collection=collection, dim=dim)
    # STEP 3: create a payload index on "site" (field_schema="keyword")
    #         so that filtering by site is fast, not a full scan

    # idempotent: re-creating an existing index is a no-op on Qdrant's side
    qdrant_client.create_payload_index(
        collection_name=collection,
        field_name="site",
        field_schema="keyword",
    )


def process_local_files(folder: str, site: str, url: str):
    """Parse → chunk → embed → upsert local files (HTML/PDF/TXT) from a folder."""
    files = sorted(os.listdir(folder))

    with logfire.span("Ingest local files", folder=folder, site=site, file_count=len(files)):
        failed = 0

        for filename in files:
            file_path = os.path.join(folder, filename)
            if not os.path.isfile(file_path):
                continue

            # "~$name.pptx" is the lock file Word/PowerPoint writes while the
            # document is OPEN — a 165-byte stub, not a real package. It matches
            # the .pptx branch below and python-pptx rejects it. Skipped quietly
            # because having a file open is normal, not an error worth logging.
            if filename.startswith("~$") or filename.startswith("."):
                continue

            with logfire.span("Processing file", filename=filename):
                try:
                    ext = os.path.splitext(filename)[1].lower()

                    if ext == ".pdf":
                        text = parse_pdf(file_path)
                    elif ext in (".html", ".htm"):
                        text = parse_html(file_path)
                    elif ext in (".txt", ".md"):
                        text = parse_text(file_path)
                    elif ext in (".docx", ".pptx"):
                        text = parse_office(file_path)
                    else:
                        logfire.warning("Skipping unsupported file", ext=ext)
                        continue

                    if not text or not text.strip():
                        logfire.warning("Skipping empty file")
                        continue

                    title = os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").title()

                    chunks = chunk_text(text, doc_title=title)
                    if not chunks:
                        logfire.warning("No chunks produced")
                        continue

                    vectors = embed_texts([c["text"] for c in chunks])

                    # local files carry no heading->id map, so every chunk cites the
                    # folder-level url with no anchor
                    points = [
                        models.PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "text": chunk["text"],
                                "source": filename,
                                "site": site,
                                "url": url,
                                "title": title,
                                "heading": chunk["ancestors"][-1] if chunk["ancestors"] else "",
                            },
                        )
                        for chunk, vector in zip(chunks, vectors)
                    ]

                    qdrant_client.upsert(
                        collection_name=settings.QDRANT_COLLECTION,
                        points=points,
                    )
                    logfire.info("Upserted", chunks=len(points))

                # One unreadable file must not discard every file already
                # ingested in this run — a corrupt PDF or a zero-byte docx is a
                # per-file problem, not a per-run one.
                except Exception as e:
                    failed += 1
                    logfire.error(
                        "Failed to process file",
                        filename=filename,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    continue

        if failed:
            logfire.warning("Some files failed", failed=failed, total=len(files))


def _resolve_anchor(ancestors: list, anchors: dict) -> tuple:
    """Pick the deepest heading in `ancestors` that has a real HTML id.

    Returns (anchor_id_or_None, levels_walked_up). Walking up matters because
    two kinds of heading never carry an id: those below the depth the crawler
    extracted (h4+), and <details><summary> labels, which are not headings in
    the HTML at all. Both have a real ancestor section that does — landing the
    reader there beats dumping them at the top of the page.
    """
    for steps, heading in enumerate(reversed(ancestors)):
        if heading in anchors:
            return anchors[heading], steps
    return None, -1


def process_crawled_site(crawled_dir: str, site: str):
    """Chunk → embed → upsert all crawled JSON files from a site folder."""
    files = sorted(f for f in os.listdir(crawled_dir) if f.endswith(".json"))

    with logfire.span("Ingest crawled site", dir=crawled_dir, site=site, file_count=len(files)):
        exact = walked = page_level = 0
        failed = 0

        for filename in files:
            file_path = os.path.join(crawled_dir, filename)

            with logfire.span("Processing page", filename=filename):
                # A truncated JSON from an interrupted crawl must cost one page,
                # not all 163 already crawled and about to be ingested.
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        page = json.load(f)

                    page_url = page.get("url", "")
                    title = page.get("title", "")
                    text = page.get("text", "")

                    if not text or not text.strip():
                        logfire.warning("Skipping empty page", url=page_url)
                        continue

                    chunks = chunk_text(text, doc_title=title)
                    if not chunks:
                        logfire.warning("No chunks produced", url=page_url)
                        continue

                    # heading text -> HTML id, as captured by the crawler
                    anchors = {h["text"]: h["id"] for h in page.get("headings", [])}

                    # embed_texts() takes plain strings; the breadcrumb is part of
                    # the text on purpose — it is what makes the vector carry the
                    # section the chunk came from
                    vectors = embed_texts([c["text"] for c in chunks])

                    source = page_url.rstrip("/").split("/")[-1] or "index"
                    points = []
                    for chunk, vector in zip(chunks, vectors):
                        anchor, steps = _resolve_anchor(chunk["ancestors"], anchors)
                        if anchor is None:
                            page_level += 1
                        elif steps == 0:
                            exact += 1
                        else:
                            walked += 1

                        points.append(
                            models.PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vector,
                                payload={
                                    "text": chunk["text"],
                                    "source": source,
                                    "site": site,
                                    # per chunk, not per page — this is the citation target
                                    "url": f"{page_url}#{anchor}" if anchor else page_url,
                                    "title": title,
                                    "heading": chunk["ancestors"][-1] if chunk["ancestors"] else "",
                                },
                            )
                        )

                    qdrant_client.upsert(
                        collection_name=settings.QDRANT_COLLECTION,
                        points=points,
                    )
                    logfire.info("Upserted", url=page_url, chunks=len(points))

                except Exception as e:
                    failed += 1
                    logfire.error(
                        "Failed to process page",
                        filename=filename,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    continue

        if failed:
            logfire.warning("Some pages failed", failed=failed, total=len(files))

        # a future crawler change shows up here as a number instead of silently
        # degrading every citation on the site
        logfire.info(
            "Citation anchors resolved",
            exact=exact,
            via_ancestor=walked,
            page_level_fallback=page_level,
        )


if __name__ == "__main__":
    # Usage:
    #   python -m app.ingestion.processor local downloaded_data/kubernetes --site kubernetes.io --url https://kubernetes.io/docs/home/ --wipe
    #   python -m app.ingestion.processor crawled crawled_data/cp-algorithms --site cp-algorithms.com --wipe

    # NOTE: same reason as crawler.py — Windows consoles default to cp1252 and
    #       mangle any non-ASCII character printed below.
    sys.stdout.reconfigure(encoding="utf-8")

    USAGE = (
        "Usage:\n"
        "  python -m app.ingestion.processor local <folder> --site <site> --url <url> [--wipe]\n"
        "  python -m app.ingestion.processor crawled <folder> --site <site> [--wipe]"
    )

    # STEP 1: parse args — mode (local/crawled), folder path, --site, --url, --wipe
    args = sys.argv[1:]

    # --wipe is a bare flag with no value, so strip it first
    wipe = "--wipe" in args
    args = [a for a in args if a != "--wipe"]

    # pull each "--flag value" pair out so the positional args stay at fixed
    # indexes no matter where the flags were typed
    def take_flag(flag: str, argv: list[str]):
        if flag not in argv:
            return None, argv
        i = argv.index(flag)
        value = argv[i + 1] if i + 1 < len(argv) else None
        if value is None or value.startswith("--"):
            print(f"{flag} needs a value after it")
            sys.exit(1)
        return value, argv[:i] + argv[i + 2:]

    site, args = take_flag("--site", args)
    url, args = take_flag("--url", args)

    if len(args) < 2:
        print(USAGE)
        sys.exit(1)

    mode, folder = args[0], args[1]

    if mode not in ("local", "crawled"):
        print(f"Unknown mode: {mode!r} — expected 'local' or 'crawled'\n{USAGE}")
        sys.exit(1)

    if not site:
        print(f"--site is required\n{USAGE}")
        sys.exit(1)

    # local files share one URL for the whole folder, so it has to be passed in;
    # crawled pages carry their own URL inside each JSON
    if mode == "local" and not url:
        print(f"--url is required for local mode\n{USAGE}")
        sys.exit(1)

    if not os.path.isdir(folder):
        print(f"Folder not found: {folder}")
        sys.exit(1)

    # STEP 2: call ensure_collection(wipe=True/False)
    ensure_collection(wipe=wipe)

    # STEP 3: call the right function based on mode
    if mode == "local":
        process_local_files(folder, site, url)
    else:
        process_crawled_site(folder, site)

    print(f"Done — ingested {folder} into collection {settings.QDRANT_COLLECTION}")