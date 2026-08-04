from typing import List
import re

import logfire

# Matches a markdown ATX heading: captures the level (# count) and the text.
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


# Tried in order when one block still exceeds the budget. Earlier separators
# preserve more meaning; "" is the last-resort hard cut that can land mid-word.
_FALLBACK_SEPARATORS = ("\n", ". ", " ", "")


def _split_oversized(text: str, limit: int, separators: tuple = _FALLBACK_SEPARATORS) -> List[str]:
    """Break one over-long block by escalating through weaker separators.

    Exists because a loader can hand us a document with no blank lines at all —
    `parse_html` joins every line with a single "\\n", so `pods_autoscale.html`
    arrived as ONE 17,731-char paragraph and became one chunk with no error and
    no warning. Escalating to "\\n" splits it on real line boundaries (max line
    there is 311 chars), so the hard character cut is a formality that almost
    never fires.

    Every returned piece is <= `limit`.
    """
    if len(text) <= limit:
        return [text]

    if not separators or separators[0] == "":
        return [text[i:i + limit] for i in range(0, len(text), limit)]

    sep, rest = separators[0], separators[1:]
    parts = [p for p in text.split(sep) if p.strip()]
    if len(parts) == 1:                      # separator absent — try a weaker one
        return _split_oversized(text, limit, rest)

    # Split ONLY — deliberately no packing here. Returning the atomic units lets
    # _pack_paragraphs group them and carry whole units as overlap. Packing to
    # `limit` in here produced ~1,450-char units that could never fit a 200-char
    # overlap budget, so structureless documents got zero overlap — exactly the
    # ones whose boundaries are arbitrary and need it most.
    out: List[str] = []
    for part in parts:
        if len(part) > limit:
            out.extend(_split_oversized(part, limit, rest))
        else:
            out.append(part)
    return out


def _pack_paragraphs(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Size-based splitter with overlap. Used INSIDE an oversized section, and
    as the whole-document fallback when no headings exist.

    Overlap is measured in whole PARAGRAPHS, never a character slice. A fenced
    code block arrives as exactly one paragraph, so paragraph-granular overlap
    can never cut through one — a character slice can, and did (63 chunks
    opened mid-C++ with a fence that closed nothing).

    Size guarantee is `chunk_size + overlap`, not `chunk_size`: a flushed chunk
    is re-seeded with up to `overlap` chars before the next paragraph is added.
    A fenced code block larger than `chunk_size` is emitted whole and exceeds
    both — deliberately; every other oversized block is broken up by
    `_split_oversized`.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    # Break up anything that alone blows the budget, EXCEPT a fenced code block:
    # splitting one orphans code from its opening fence, and half a listing is
    # worse than a long one. Done up front so the pieces then pack normally with
    # their neighbours instead of each becoming a lone chunk.
    expanded: List[str] = []
    for para in paragraphs:
        if len(para) > chunk_size and not para.lstrip().startswith("```"):
            expanded.extend(_split_oversized(para, chunk_size))
        else:
            expanded.append(para)
    paragraphs = expanded

    chunks: List[str] = []
    current: List[str] = []   # paragraphs in the chunk being built
    size = 0

    def flush() -> None:
        """Emit `current`, then seed the next chunk with as many whole trailing
        paragraphs as fit the overlap budget."""
        nonlocal current, size
        if not current:
            return
        chunks.append("\n\n".join(current))

        keep: List[str] = []
        total = 0
        for para in reversed(current):
            if total + len(para) > overlap:
                break
            keep.insert(0, para)
            total += len(para)
        current, size = keep, total

    for para in paragraphs:
        # An oversized paragraph is almost always one fenced code block. Emit it
        # whole rather than cutting it mid-listing, and carry no overlap off it —
        # its tail is the end of a code listing, which is noise leading the next
        # chunk.
        if len(para) > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
            chunks.append(para)
            current, size = [], 0
            continue

        if current and size + len(para) >= chunk_size:
            flush()

        current.append(para)
        size += len(para)

    if current:
        chunks.append("\n\n".join(current))

    return [c.strip() for c in chunks if c.strip()]

def _split_into_sections(text: str) -> List[tuple]:
    """Split markdown into (ancestors, body) pairs, one per heading.

    `ancestors` is the heading trail from the top down to this section, e.g.
    ["Binary Exponentiation", "Algorithm", "Recursive approach"]
    -> breadcrumb  " > ".join(ancestors)
    -> own heading ancestors[-1]

    Text before the first heading is returned with ancestors == [].
    """
    # STEP 1: find the character ranges covered by fenced code blocks.
    #         Scan for ``` and pair them up: 1st opens, 2nd closes, 3rd opens...
    #         Keep a list of (start, end) spans, or a helper that answers
    #         "is this position inside a code block?"
    fences = [m.start() for m in re.finditer(r"```", text)]

    code_spans: List[tuple] = []
    for i in range(0, len(fences) - 1, 2):
        code_spans.append((fences[i], fences[i + 1] + 3))

    # an odd fence count means the last one never closed — treat it as running
    # to the end of the document rather than ignoring it
    if len(fences) % 2 == 1:
        code_spans.append((fences[-1], len(text)))

    def in_code(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_spans)

    # STEP 2: collect headings with HEADING_RE.finditer(text), DISCARDING any
    #         match whose .start() lands inside a span from STEP 1.
    #         For each surviving match you need:
    #           level = len(match.group(1))   -> "###" is 3
    #           title = match.group(2)
    #           body starts at match.end()
    #           heading starts at match.start()
    headings = [m for m in HEADING_RE.finditer(text) if not in_code(m.start())]

    # STEP 3: if NO headings survive, return [([], text)] so the caller falls
    #         back to _pack_paragraphs on the whole document.
    if not headings:
        return [([], text)]

    sections: List[tuple] = []

    # STEP 4: text before the first heading is a preamble — if it has content,
    #         emit it as ([], preamble_text).
    preamble = text[: headings[0].start()]
    if preamble.strip():
        sections.append(([], preamble))

    # STEP 5: walk the headings in order, maintaining a STACK of (level, title).
    #         For a heading at level L:
    #           - pop every entry whose level is >= L
    #           - push (L, title)
    #           - ancestors = [title for _, title in stack]
    #
    #         Walking  ## A, ### B, ### C, ## D:
    #           ## A   push          stack [A]      -> ["A"]
    #           ### B  push          stack [A, B]   -> ["A", "B"]
    #           ### C  pop B, push   stack [A, C]   -> ["A", "C"]
    #           ## D   pop C and A   stack [D]      -> ["D"]
    stack: List[tuple] = []
    for i, match in enumerate(headings):
        level = len(match.group(1))
        title = match.group(2)

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

        # the comprehension already builds a NEW list, so later pops on `stack`
        # can't reach back and mutate what we hand out here
        ancestors = [t for _, t in stack]

        # STEP 6: this section's body runs from its match.end() to the START of the
        #         next surviving heading — or to the end of `text` for the last one.
        #         Take a COPY of the ancestors list (list(...)), not a reference —
        #         the stack keeps mutating as you walk.
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append((ancestors, text[match.end():body_end]))

    # STEP 7: return the list of (ancestors, body) pairs. Sections with an empty
    #         body still count — a heading with no text under it is a real
    #         section, and the caller decides whether to drop it.
    return sections

def chunk_text(
    text: str,
    chunk_size: int = 1500,
    overlap: int = 200,
    doc_title: str = "",
) -> List[dict]:
    """Structure-aware chunking: split on headings, prefix each chunk with its
    breadcrumb so the embedding carries the section it came from.

    Returns dicts: {"text": <breadcrumb + body>, "heading": <own heading or "">}
    `heading` is what the caller maps to an HTML anchor for citations.
    """
    with logfire.span("✂️ Structure-aware chunking", text_length=len(text)):
        # STEP 1: return [] if text is empty/whitespace
        if not text or not text.strip():
            return []

        # STEP 2: sections = _split_into_sections(text)
        sections = _split_into_sections(text)

        chunks: List[dict] = []

        # STEP 3: for each (ancestors, body) in sections:
        for ancestors, body in sections:

            #   STEP 3a: skip if body is empty/whitespace.
            #            Container headings like "Applications" have no body of their
            #            own — measured at 63 of 1,184 sections on cp-algorithms.
            body = body.strip()
            if not body:
                continue

            #   STEP 3b: build the breadcrumb PARTS.
            #            Start from `ancestors`, and prepend doc_title ONLY IF
            #            doc_title is set AND it isn't already ancestors[0].
            #            On all 163 crawled pages ancestors[0] IS the page title
            #            (the crawler reads the title from the body's first "# " line),
            #            so an unconditional prepend gives
            #            "Binary Exponentiation > Binary Exponentiation > Algorithm".
            #            Then breadcrumb = " > ".join(parts)
            parts = list(ancestors)
            if doc_title and (not parts or parts[0] != doc_title):
                parts.insert(0, doc_title)
            breadcrumb = " > ".join(parts)

            #   STEP 3c: split the body if needed.
            #            fits -> [body]
            #            else -> _pack_paragraphs(body, chunk_size, overlap)
            #            Every piece keeps the SAME breadcrumb — that's the point:
            #            three pieces of one section all still say which section.
            #            NOTE: the breadcrumb adds to the final chunk length. Decide
            #            whether the budget you pass is `chunk_size` or
            #            `chunk_size - len(breadcrumb)`. Either is defensible; just
            #            know which one you chose.
            #
            #            CHOSEN: `chunk_size - len(prefix)`, so chunk_size stays a
            #            promise about the FINAL text that gets embedded, not about
            #            an intermediate the caller never sees. Floored at half
            #            chunk_size so a freakishly long breadcrumb can't shrink the
            #            budget to nothing and shred the body into scraps.
            prefix = f"{breadcrumb}\n\n" if breadcrumb else ""
            budget = max(chunk_size - len(prefix), chunk_size // 2)

            pieces = [body] if len(body) <= budget else _pack_paragraphs(body, budget, overlap)

            for piece in pieces:
                #   STEP 3d: prefix each piece -> f"{breadcrumb}\n\n{piece}"
                #            When breadcrumb is empty (a preamble section with no
                #            ancestors), use the piece unchanged — don't emit a
                #            leading blank line.
                #   STEP 3e: append {"text": <prefixed piece>,
                #                    "heading": ancestors[-1] if ancestors else ""}
                #            Note: `heading` is this section's OWN heading, not the
                #            breadcrumb — the caller looks it up in the crawled page's
                #            `headings` list to get the HTML anchor.
                chunks.append({
                    "text": f"{prefix}{piece}",
                    "ancestors": list(ancestors),      # full trail, most-general first
                })

        # STEP 4: logfire.info the chunk count, then return chunks
        logfire.info(
            "Chunked document",
            sections=len(sections),
            chunks=len(chunks),
        )
        return chunks