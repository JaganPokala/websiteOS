// --- Imports: React ---
import { useRef, useState } from "react";

// --- Imports: third-party ---
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

// --- Imports: local ---
import { IconCheck, IconCopy } from "./Icons";

// Fenced code blocks get their own wrapper with a language label and a copy
// button. rehype-highlight has already added .hljs-* classes to the tokens
// inside; index.css colours those classes per theme.
function CodeBlock({ children, className }) {
  const [copied, setCopied] = useState(false);
  // A ref to the <code> node, so copy() can read the rendered text straight from
  // the DOM instead of trying to flatten React's children tree back into a string.
  const codeRef = useRef(null);
  // rehype-highlight puts the language on the <code> as "language-yml hljs ..."
  const lang = /language-(\w+)/.exec(className || "")?.[1] || "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(codeRef.current?.innerText ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500); // revert the label after a beat
    } catch {
      /* clipboard blocked (e.g. insecure context) — fail quietly */
    }
  }

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-zinc-200 dark:border-ink-700">
      <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-3 py-1.5 dark:border-ink-700 dark:bg-ink-850">
        <span className="font-mono text-[11px] tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
          {lang || "code"}
        </span>
        <button
          onClick={copy}
          className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12px] text-zinc-500 transition hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-ink-800 dark:hover:text-zinc-100"
        >
          {copied ? <IconCheck width={13} height={13} /> : <IconCopy width={13} height={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {/* overflow-x-auto so long lines scroll INSIDE the block, never widening the page */}
      <pre className="overflow-x-auto bg-white p-3 dark:bg-ink-900">
        <code
          ref={codeRef}
          className={(className || "") + " font-mono text-[13px] leading-relaxed"}
        >
          {children}
        </code>
      </pre>
    </div>
  );
}

// Map each markdown element to a Tailwind-styled version. Doing it here (rather
// than a prose plugin) keeps the styling consistent with the rest of the app.
const components = {
  p: (props) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />,
  h1: (props) => <h1 className="mt-4 mb-2 text-lg font-semibold first:mt-0" {...props} />,
  h2: (props) => <h2 className="mt-4 mb-2 text-base font-semibold first:mt-0" {...props} />,
  h3: (props) => <h3 className="mt-3 mb-1.5 text-sm font-semibold first:mt-0" {...props} />,
  ul: (props) => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
  ol: (props) => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
  li: (props) => <li className="leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  a: (props) => (
    // Links come from model output, so open them in a new tab and add
    // noreferrer — never let generated content control the current page.
    <a
      className="text-brand-500 underline underline-offset-2 hover:text-brand-400"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  blockquote: (props) => (
    <blockquote
      className="my-3 border-l-2 border-brand-500/40 pl-3 text-zinc-600 italic dark:text-zinc-400"
      {...props}
    />
  ),
  hr: () => <hr className="my-4 border-zinc-200 dark:border-ink-700" />,
  table: (props) => (
    // The wrapper scrolls, so a wide table never stretches the chat column.
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...props} />
    </div>
  ),
  th: (props) => (
    <th
      className="border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-left font-semibold dark:border-ink-700 dark:bg-ink-850"
      {...props}
    />
  ),
  td: (props) => (
    <td className="border border-zinc-200 px-2.5 py-1.5 dark:border-ink-700" {...props} />
  ),
  code: ({ inline, className, children, ...props }) => {
    // react-markdown calls this for BOTH `inline code` and fenced blocks.
    // Fenced blocks carry a language- class; inline ones don't.
    const isBlock = /language-/.test(className || "");
    if (!inline && isBlock) {
      return (
        <CodeBlock className={className} {...props}>
          {children}
        </CodeBlock>
      );
    }
    return (
      <code
        className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[13px] text-brand-600 dark:bg-ink-800 dark:text-brand-300"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: (props) => <>{props.children}</>, // CodeBlock supplies its own <pre>
};

export default function Markdown({ children }) {
  return (
    <ReactMarkdown
      // remark-gfm adds tables, strikethrough, task lists, autolinks.
      // No rehype-raw: raw HTML in model output stays inert, which is the
      // safe default — we never inject arbitrary markup into the page.
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={components}
    >
      {children}
    </ReactMarkdown>
  );
}
