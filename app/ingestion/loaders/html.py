# --- Imports ---
import logfire
from bs4 import BeautifulSoup

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]

# Block-level elements worth keeping, in the order find_all returns them
# (document order) — that ordering is what keeps a heading attached to the
# text beneath it.
BLOCK_TAGS = HEADING_TAGS + ["p", "li", "pre", "blockquote" , "table"]


def parse_html(file_path: str):
    """
    Parse HTML into MARKDOWN-ish text that preserves heading structure.

    Returns text where headings are ATX markdown ("## Section") and blocks are
    separated by blank lines — the two things the chunker needs. The previous
    version called soup.get_text(), which deleted every <h1>-<h6> and joined
    lines with a single "\\n", so a whole page arrived as one paragraph with no
    structure (pods_autoscale.html: 29 headings destroyed, 17,731 chars, 1 chunk).
    """
    with logfire.span("📄 HTML Parsing", filename=file_path):
        try:
            # STEP 1: read the file and build the soup (unchanged)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            soup = BeautifulSoup(content, "html.parser")

            # STEP 2: decompose the junk. Keep the existing
            #         ["script", "style", "meta", "noscript"] and consider adding
            #         ["nav", "header", "footer", "aside", "form"] — site chrome
            #         that repeats on every page and pollutes every chunk.
            for junk in soup(["script", "style", "meta", "noscript",
                              "nav", "header", "footer", "aside", "form"]):
                junk.decompose()

            # STEP 3: walk the block-level elements IN DOCUMENT ORDER and turn
            #         each into a string:
            #           soup.find_all(["h1","h2","h3","h4","h5","h6",
            #                          "p", "li", "pre", "blockquote"])
            #         find_all returns document order, which is what keeps a
            #         heading attached to the text beneath it.
            blocks = []
            for tag in soup.find_all(BLOCK_TAGS):
                # A <p> inside a <li>, or a <li> inside a nested <ul>, is already
                # covered by its ancestor's get_text(). Emitting both would put the
                # same sentence in the document twice.
                if tag.find_parent(BLOCK_TAGS):
                    continue

                #   STEP 3a: for a heading tag, emit "#" * level + " " + text
                #            level = int(tag.name[1])
                if tag.name in HEADING_TAGS:
                    level = int(tag.name[1])
                    #   STEP 3c: use tag.get_text(" ", strip=True) so inline tags
                    #            (<code>, <a>, <strong>) don't glue words together
                    text = tag.get_text(" ", strip=True)
                    #   STEP 3d: skip blocks whose text is empty after stripping
                    if not text:
                        continue
                    blocks.append("#" * level + " " + text)

                # <pre> is the one place " ".join is wrong: it flattens a C++
                # listing onto one line. Keep the literal newlines and fence it —
                # the chunker treats a ```-opening paragraph as unsplittable, so
                # the listing survives whole instead of being cut mid-function.
                elif tag.name == "pre":
                    code = tag.get_text().strip("\n").rstrip()
                    if not code.strip():
                        continue
                    blocks.append(f"```\n{code}\n```")
                elif tag.name == "table":
                    rows = []
                    for tr in tag.find_all("tr"):
                        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        blocks.append("\n".join(rows))

                #   STEP 3b: for everything else, emit the text as-is
                else:
                    text = tag.get_text(" ", strip=True)
                    if not text:
                        continue
                    blocks.append(text)

            # STEP 4: join the blocks with "\n\n".
            #         This is the part that makes _pack_paragraphs work — it
            #         splits on blank lines, and the old single-"\n" output had
            #         none at all.
            text_clean = "\n\n".join(blocks)

            # STEP 5: return the joined text
            return text_clean

        except Exception as e:
            logfire.error(f"❌ HTML Parse Failed: {e}")
            raise e