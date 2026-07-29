// --- Imports: React ---
import { useEffect, useRef, useState } from "react";

// --- Imports: local ---
import { IconChevron, IconQuote } from "./Icons";
import Markdown from "./Markdown";

function Avatar({ role, initial }) {
  return role === "assistant" ? (
    <span className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 text-[12px] font-bold text-white">
      W
    </span>
  ) : (
    <span className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-zinc-200 text-[12px] font-semibold text-zinc-600 dark:bg-ink-800 dark:text-zinc-300">
      {initial}
    </span>
  );
}

function RoleLabel({ children }) {
  return (
    <div className="mb-1 text-[12px] font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">
      {children}
    </div>
  );
}

// Turn one retrieved chunk into a short preview line.
// Sources are plain strings today (the retriever prefixes them with "CONTENT: ").
// Handling objects too means this keeps working once chunks carry a url/title.
function preview(raw) {
  const text =
    typeof raw === "string" ? raw : (raw?.content ?? raw?.text ?? JSON.stringify(raw));
  const clean = String(text)
    .replace(/^CONTENT:\s*/i, "") // drop the retriever's prefix
    .replace(/\s+/g, " ") // collapse newlines so previews stay 1-2 lines
    .trim();
  return clean.length > 200 ? clean.slice(0, 200).trimEnd() + "…" : clean;
}

// Collapsed by default — the answer stays the focus, and the evidence is one
// click away. `open` lives here, not in the parent: no other component cares.
function Sources({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-[13px] font-medium text-zinc-600 transition hover:border-zinc-300 hover:text-zinc-900 dark:border-ink-700 dark:bg-ink-850 dark:text-zinc-400 dark:hover:border-ink-600 dark:hover:text-zinc-100"
      >
        <IconQuote width={14} height={14} />
        {sources.length} source{sources.length === 1 ? "" : "s"}
        <IconChevron
          width={14}
          height={14}
          className={"transition-transform " + (open ? "rotate-180" : "")}
        />
      </button>

      {open && (
        <ol className="mt-2 flex flex-col gap-2">
          {sources.map((src, i) => (
            <li
              key={i}
              className="flex gap-2.5 rounded-lg border border-zinc-200 bg-white p-3 dark:border-ink-800 dark:bg-ink-900"
            >
              <span className="grid h-5 w-5 flex-none place-items-center rounded-md bg-brand-500/10 text-[11px] font-semibold text-brand-500">
                {i + 1}
              </span>
              <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                {preview(src)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// Shown between "send" and the first token — the ~14s the pipeline spends on
// guardrails, planning and retrieval. `status` is the stage name the backend sent.
function ThinkingIndicator({ status }) {
  return (
    <div className="flex gap-3.5">
      <Avatar role="assistant" />
      <div className="min-w-0 flex-1">
        <RoleLabel>WebsiteOS</RoleLabel>
        {/* Text first, dots after — so they read as an animated ellipsis
            ("Searching your sites …") rather than a separate spinner. */}
        <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
          <span>{status || "Working"}</span>
          {/* Nudged down so the dots rest at the text baseline like an ellipsis.
              The bounce lifts them 3px, so this offset makes them oscillate
              around the baseline instead of sitting above centre. */}
          <span className="flex translate-y-[4px] items-center gap-0.5">
            {/* Same animation on each dot, offset in time -> a travelling wave */}
            <span className="dot" style={{ animationDelay: "0ms" }} />
            <span className="dot" style={{ animationDelay: "150ms" }} />
            <span className="dot" style={{ animationDelay: "300ms" }} />
          </span>
        </div>
      </div>
    </div>
  );
}

export default function MessageList({
  messages,
  loading,
  streamingText,
  streamingSources,
  status,
  thinking,
  userInitial,
  conversationId,
}) {
  // useRef holds a value that survives re-renders WITHOUT triggering one.
  // Attached via ref={bottomRef}, it gives us the real DOM node to scroll to.
  const bottomRef = useRef(null);

  // Which conversation we've already done the initial jump-to-bottom for.
  // Opening a chat with a long history and SMOOTH-scrolling all the way down
  // is exactly the bug being fixed here — the user watches the whole history
  // scroll past before landing on the last message, like ChatGPT never would.
  // The fix: the FIRST render of a given conversation's messages jumps there
  // instantly; only updates AFTER that (a new token, a new message) animate.
  const scrolledForRef = useRef(null);

  useEffect(() => {
    if (loading) return; // nothing real is rendered yet — bottomRef isn't mounted

    // Guard against a subtle race: this effect can also fire on a transient
    // render where `loading` is already false but the real messages (and
    // therefore this ref's DOM node) haven't landed yet. Marking "already
    // scrolled" on THAT no-op run would consume the one-time instant-jump
    // flag before it ever did anything — leaving the real render, moments
    // later, to incorrectly animate in "smooth" instead of jumping straight
    // there. Only commit to having scrolled when there was a node to scroll.
    const node = bottomRef.current;
    if (!node) return;

    const isFirstRenderForThisChat = scrolledForRef.current !== conversationId;
    node.scrollIntoView({
      behavior: isFirstRenderForThisChat ? "auto" : "smooth",
      block: "end",
    });
    scrolledForRef.current = conversationId;
  }, [messages, streamingText, status, loading, conversationId]);

  // RULES OF HOOKS: every hook above must run on every render, in the same order.
  // That's why the early returns come AFTER them, never before.
  if (loading) {
    return <p className="text-sm text-zinc-400 dark:text-zinc-500">Loading messages…</p>;
  }

  if (messages.length === 0 && !streamingText && !thinking) {
    return (
      <p className="text-sm text-zinc-400 dark:text-zinc-500">
        No messages yet. Ask something to get started.
      </p>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-7">
      {messages.map((msg) => (
        <div key={msg.id} className="flex gap-3.5">
          <Avatar role={msg.role} initial={userInitial} />
          <div className="min-w-0 flex-1">
            <RoleLabel>{msg.role === "user" ? "You" : "WebsiteOS"}</RoleLabel>
            {/* Only the assistant writes markdown. User text is rendered as-is so
                a question containing * or # shows exactly what they typed. */}
            {msg.role === "assistant" ? (
              <div className="min-w-0 break-words">
                <Markdown>{msg.content}</Markdown>
              </div>
            ) : (
              <div className="leading-relaxed break-words whitespace-pre-wrap">
                {msg.content}
              </div>
            )}
            {/* Historical messages carry their sources from the DB (jsonb column) */}
            {msg.role === "assistant" && <Sources sources={msg.sources} />}
          </div>
        </div>
      ))}

      {/* Before any token arrives, show the stage indicator. Once text starts
          streaming it takes over — the answer replaces the placeholder in place. */}
      {thinking && !streamingText && <ThinkingIndicator status={status} />}

      {streamingText && (
        <div className="flex gap-3.5">
          <Avatar role="assistant" />
          <div className="min-w-0 flex-1">
            <RoleLabel>WebsiteOS</RoleLabel>
            {/* Markdown is re-parsed on every token. Partial syntax (an unclosed
                ``` fence, say) renders as best it can and resolves as more arrives. */}
            <div className="min-w-0 break-words">
              <Markdown>{streamingText}</Markdown>
              <span className="caret" />
            </div>
            <Sources sources={streamingSources} />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
