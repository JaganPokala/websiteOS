// --- Imports: React ---
import { useState } from "react";

// --- Imports: local ---
import { IconSend } from "./Icons";

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState("");

  function submit() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    setText(""); // clear immediately so it feels responsive
    onSend(trimmed); // hand the question up to ChatApp
  }

  function handleSubmit(e) {
    e.preventDefault();
    submit();
  }

  function handleKeyDown(e) {
    // Chat convention: Enter sends, Shift+Enter makes a new line.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-2 pl-4 shadow-sm transition focus-within:border-brand-500/60 focus-within:ring-4 focus-within:ring-brand-500/10 dark:border-ink-700 dark:bg-ink-900"
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask anything about your indexed sites…"
        rows={1}
        disabled={disabled}
        className="max-h-48 flex-1 resize-none border-none bg-transparent py-2 leading-relaxed outline-none placeholder:text-zinc-400 disabled:opacity-60 dark:placeholder:text-zinc-600"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        aria-label="Send message"
        className="grid h-9 w-9 flex-none place-items-center rounded-xl bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <IconSend />
      </button>
    </form>
  );
}
