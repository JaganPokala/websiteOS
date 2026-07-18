"""
Delete all Qdrant points with a given source_type (or a specific source file).

Usage:
    python -m app.ingestion.delete_by_source_type noisy
    python -m app.ingestion.delete_by_source_type noisy --file report.pdf
    python -m app.ingestion.delete_by_source_type noisy --count   # just count, don't delete
"""
import sys
import logfire

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings

logfire.configure(service_name="enterprise-ingestion-service")

client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=120)


def ensure_payload_indexes():
    """Qdrant requires a keyword payload index before filtering on a field."""
    for field in ("source_type", "source"):
        try:
            client.create_payload_index(
                collection_name=settings.QDRANT_COLLECTION,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logfire.info(f"Created payload index for '{field}'.")
        except Exception as e:
            # Already exists (or another benign error) — safe to ignore.
            logfire.debug(f"Payload index for '{field}' not created: {e}")


def build_filter(source_type: str, file: str | None) -> models.Filter:
    must = [models.FieldCondition(key="source_type", match=models.MatchValue(value=source_type))]
    if file:
        must.append(models.FieldCondition(key="source", match=models.MatchValue(value=file)))
    return models.Filter(must=must)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m app.ingestion.delete_by_source_type <source_type> [--file NAME] [--count]")
        sys.exit(1)

    source_type = args[0]
    file = None
    if "--file" in args:
        file = args[args.index("--file") + 1]
    count_only = "--count" in args

    scope = f"source_type='{source_type}'" + (f", source='{file}'" if file else "")

    with logfire.span("Delete by source_type", source_type=source_type, file=file, count_only=count_only):
        ensure_payload_indexes()
        flt = build_filter(source_type, file)

        n = client.count(settings.QDRANT_COLLECTION, count_filter=flt, exact=True).count
        logfire.info(f"Matched {n} points for {scope} in '{settings.QDRANT_COLLECTION}'.")
        print(f"Matched {n} points for {scope} in '{settings.QDRANT_COLLECTION}'.")

        if count_only or n == 0:
            return

        confirm = input(f"Delete these {n} points? [y/N] ").strip().lower()
        if confirm != "y":
            logfire.info("Delete aborted by user.")
            print("Aborted.")
            return

        client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=models.FilterSelector(filter=flt),
        )
        logfire.info(f"Deleted {n} points for {scope}.")
        print(f"Deleted {n} points.")


if __name__ == "__main__":
    main()