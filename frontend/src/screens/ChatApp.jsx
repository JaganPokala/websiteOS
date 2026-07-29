// --- Imports: React ---
import { useEffect, useRef, useState } from "react";

// --- Imports: local ---
import * as api from "../lib/api";
import ChatInput from "../components/ChatInput";
import { IconClose, IconSidebar } from "../components/Icons";
import MessageList from "../components/MessageList";
import Sidebar from "../components/Sidebar";

// Below this width the sidebar can't share space with the chat — it becomes an
// overlay drawer instead of a permanent column. Matches Tailwind's `md` breakpoint
// so this JS check and any md: utility classes agree on the same cutoff.
const MOBILE_QUERY = "(max-width: 767px)";

// Drag-to-resize bounds for the desktop sidebar — narrow enough to still fit
// "New chat" + a title, wide enough that it can't swallow the whole screen.
const MIN_SIDEBAR_WIDTH = 220;
const MAX_SIDEBAR_WIDTH = 420;
const DEFAULT_SIDEBAR_WIDTH = 272;
const SIDEBAR_WIDTH_KEY = "sidebar_width";

// Container component: owns all the state and the API calls, then hands data +
// callbacks down to the presentational children (Sidebar, MessageList, ChatInput).
export default function ChatApp({ user, onLogout, theme, onToggleTheme }) {
  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState(null); // which chat is open
  const [messages, setMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [streamingText, setStreamingText] = useState(""); // the answer as it arrives
  const [streamingSources, setStreamingSources] = useState([]); // retrieved chunks
  const [status, setStatus] = useState(""); // which pipeline stage we're on
  // The SET of conversation ids currently generating an answer — not a single
  // id, so more than one chat can be mid-stream at once. Chats are otherwise
  // independent (own messages, own database row), so there's no real reason
  // sending in one should block sending in another; only sending TWICE into
  // the SAME chat at once needs preventing. `null` is a valid member of this
  // set too — it's the placeholder key used while sending from the home
  // screen, before a brand-new conversation has a real id yet (see below).
  const [sendingIds, setSendingIds] = useState(() => new Set());
  const [collapsed, setCollapsed] = useState(false); // desktop: rail vs full sidebar
  const [error, setError] = useState("");

  // Desktop sidebar width, drag-adjustable. Lazy initialiser reads any saved
  // width once on mount instead of flashing the default then jumping to it.
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return saved >= MIN_SIDEBAR_WIDTH && saved <= MAX_SIDEBAR_WIDTH ? saved : DEFAULT_SIDEBAR_WIDTH;
  });
  // True only while the handle is actively being dragged — turns off the
  // grid's CSS transition (which exists for the collapse/expand animation)
  // so the drag tracks the cursor instantly instead of easing behind it.
  const [isResizing, setIsResizing] = useState(false);

  // Are we on a small screen right now? The lazy initialiser reads this once on
  // first render instead of assuming desktop and flashing the wrong layout.
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);
  // On mobile the sidebar is a drawer: closed by default so the chat gets the
  // whole screen. It's a SEPARATE piece of state from `collapsed` — desktop
  // "collapsed to a rail" and mobile "hidden off-screen" are different mechanisms.
  const [mobileOpen, setMobileOpen] = useState(false);

  // Stay in sync as the window crosses the breakpoint (resize, rotate, or the
  // devtools responsive-mode toggle) rather than only checking once at mount.
  useEffect(() => {
    const mql = window.matchMedia(MOBILE_QUERY);
    const handleChange = (e) => setIsMobile(e.matches);
    mql.addEventListener("change", handleChange);
    return () => mql.removeEventListener("change", handleChange);
  }, []);

  // Growing back past the breakpoint with the drawer open would otherwise leave
  // it stuck open (now as an unwanted overlay) once we're back on desktop.
  useEffect(() => {
    if (!isMobile) setMobileOpen(false);
  }, [isMobile]);

  function handleToggleSidebar() {
    if (isMobile) setMobileOpen((open) => !open);
    else setCollapsed((c) => !c);
  }

  // Persist the chosen width so a reload remembers it, same idea as the JWT
  // living in localStorage — it's a UI preference, not conversation data.
  useEffect(() => {
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  // The handle only calls this on mousedown; the actual tracking happens in
  // the effect below, which attaches window-level listeners for the duration
  // of the drag. Window-level (not just on the handle) because the cursor
  // moves faster than a 6px-wide strip can keep up with once dragging starts.
  function handleResizeStart(e) {
    e.preventDefault();
    setIsResizing(true);
  }

  useEffect(() => {
    if (!isResizing) return;

    function handleMouseMove(e) {
      const next = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, e.clientX));
      setSidebarWidth(next);
    }
    function handleMouseUp() {
      setIsResizing(false);
    }

    // Cursor + text-selection would otherwise fight the drag — e.g. fast
    // mouse movement selecting sidebar text instead of just resizing it.
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  // When we create a conversation and immediately send to it, we already know
  // it's empty — and fetching its (empty) message list would wipe the optimistic
  // user message we just added. A ref is right here: we need to remember a fact
  // across renders WITHOUT causing one.
  const skipNextLoad = useRef(false);

  // The LATEST selectedId, readable from inside a stream's callbacks. A plain
  // closure over `selectedId` would only ever see the value from the moment
  // handleSend was called — never a later switch to a different chat. Kept in
  // sync by the effect below so an in-flight stream can tell "am I still the
  // conversation on screen, or did the user navigate away from me?"
  const selectedIdRef = useRef(selectedId);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  // --- load the conversation list once, on mount ---
  useEffect(() => {
    api
      .listConversations()
      .then(setConversations)
      .catch((err) => setError(err.message));
  }, []); // [] = run once

  // Switching conversations must clear the previous chat's messages/streaming
  // state in the SAME synchronous update as changing selectedId — NOT inside
  // a useEffect that only runs after that render has already committed.
  // Effects fire one render late, by design; a plain setSelectedId(id) here
  // would otherwise briefly commit a render where `selectedId` is already the
  // new chat but `messages` is still the OLD chat's. That's not just visually
  // wrong — MessageList's own effect (which decides instant-vs-smooth scroll
  // based on whether a conversation's messages just loaded for the first
  // time) would see that stale mismatch, think the new chat's content had
  // already loaded, and mark it "already scrolled" before it ever really was.
  // Every subsequent switch after the first one hit exactly this, which is
  // why only the very first conversation opened after a reload ever animated
  // correctly. Batching all of this into one update closes the gap entirely.
  function switchToConversation(id) {
    if (id === selectedId) return; // already open — re-clicking should be a no-op
    setStreamingText("");
    setStreamingSources([]);
    setStatus("");
    setError("");
    setMessages([]);
    setSelectedId(id);
  }

  // --- load messages whenever the SELECTED conversation changes ---
  // The [selectedId] dependency list is the key part: React re-runs this effect
  // every time selectedId changes. Click a different chat -> its messages load.
  // (Clearing old state now happens in switchToConversation, above, so this
  // effect's job is purely "fetch the new chat's messages from the backend".)
  useEffect(() => {
    if (!selectedId) {
      return;
    }
    if (skipNextLoad.current) {
      skipNextLoad.current = false; // brand-new chat: nothing to fetch
      return;
    }
    let cancelled = false; // guards against a slow response arriving late
    setLoadingMessages(true);
    api
      .getMessages(selectedId)
      .then((rows) => {
        if (!cancelled) setMessages(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingMessages(false);
      });

    // Cleanup: React runs this before the next effect (i.e. if you click another
    // chat quickly). It stops an older, slower request from overwriting newer data.
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function handleNewChat() {
    setError(""); // a stale error from a previous action shouldn't outlive this new one
    try {
      const conv = await api.createConversation();
      // Functional update: React gives you the latest state as `prev`, which is
      // safer than referencing `conversations` directly (that value could be stale).
      setConversations((prev) => [conv, ...prev]);
      switchToConversation(conv.id);
    } catch (err) {
      setError(err.message);
    }
  }

  // Which conversation (if any) is awaiting delete confirmation. An id, not a
  // boolean — the confirm modal below needs it to look up the title to show.
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  // window.confirm() is a native browser dialog — sandboxed/embedded contexts
  // (iframes without allow-modals, e.g. an in-app preview) block it entirely,
  // and per spec it then just returns false with nothing ever shown. That
  // silently skips the delete instead of confirming it. An in-app modal
  // (rendered below, same idea as the error toast) doesn't depend on the
  // browser allowing anything — it's just our own React state.
  function handleDelete(id) {
    setConfirmDeleteId(id);
  }

  async function confirmDelete() {
    const id = confirmDeleteId;
    setConfirmDeleteId(null);
    setError(""); // a stale error from a previous action shouldn't outlive this new one
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (selectedId === id) switchToConversation(null); // close it if it was open
    } catch (err) {
      setError(err.message);
    }
  }

  // --- send a question and stream the answer back ---
  async function handleSend(text) {
    // The lock key for THIS call: the chat it's sending into, or null if it's
    // about to create a brand-new one from the home screen. Only blocks a
    // second send into the SAME key — a different chat's key is untouched.
    const lockKey = selectedId;
    if (sendingIds.has(lockKey)) return;
    setError("");
    setStreamingText("");
    setStreamingSources([]);
    setStatus(""); // the indicator shows "Working…" until the first stage arrives
    setSendingIds((prev) => new Set(prev).add(lockKey));

    let convId = selectedId;
    // Fixed for this call: does the chat we're streaming for still match
    // whatever the user is CURRENTLY looking at? Checked before every screen
    // update below, since the user is free to switch chats while this awaits.
    const belongsHere = () => selectedIdRef.current === convId;

    try {
      // Sent from the home screen with no chat open? Create one first, the way
      // ChatGPT does — the user never has to click "New chat".
      if (!convId) {
        const conv = await api.createConversation();
        skipNextLoad.current = true; // it's empty; don't let the fetch clear our message
        setConversations((prev) => [conv, ...prev]);
        setSelectedId(conv.id);
        convId = conv.id;
        // Swap the placeholder `null` lock for the real id now that we have one.
        setSendingIds((prev) => {
          const next = new Set(prev);
          next.delete(null);
          next.add(conv.id);
          return next;
        });
        setMessages([]); // fresh chat starts clean
      }

      // Optimistic update: show the user's own message immediately instead of
      // waiting for a round-trip. The backend saves its own copy.
      const userMsg = { id: `local-user-${Date.now()}`, role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);

      // Accumulate locally too: state updates are async, so we can't read the final
      // streamingText right after the loop — but these locals are always current.
      let full = "";
      let collectedSources = [];

      await api.streamQuery(convId, text, {
        onToken: (token) => {
          full += token;
          // Guarded: if the user has switched to a different chat, this token
          // belongs to a conversation that's no longer on screen — showing it
          // here would be exactly the cross-chat bleed we're fixing.
          if (belongsHere()) {
            // Functional update is ESSENTIAL here. `streamingText + token` would use
            // the value captured when this callback was created (a stale closure),
            // so tokens would overwrite each other instead of appending.
            setStreamingText((prev) => prev + token);
          }
        },
        onStatus: (s) => {
          if (belongsHere()) setStatus(s); // "Checking your question" -> "Searching your sites" -> ...
        },
        onSources: (docs) => {
          collectedSources = docs; // for the finished message, regardless of where the user is
          if (belongsHere()) setStreamingSources(docs); // shown live only if still relevant
        },
      });

      // Stream finished -> promote the accumulated text into a real message,
      // but ONLY if we're still looking at the conversation it belongs to.
      // If the user navigated away, we don't need to do anything else here —
      // the backend already saved this exact message under `convId` via
      // add_message() inside /query/stream, so it's already sitting in the
      // database and will load correctly next time that chat is opened.
      if (belongsHere()) {
        setMessages((prev) => [
          ...prev,
          {
            id: `local-asst-${Date.now()}`,
            role: "assistant",
            content: full,
            sources: collectedSources,
          },
        ]);
      }
    } catch (err) {
      // Also guarded — an error for an abandoned background stream shouldn't
      // pop up on whatever unrelated chat the user has since switched to.
      if (belongsHere()) setError(err.message);
    } finally {
      if (belongsHere()) {
        setStreamingText("");
        setStreamingSources([]);
        setStatus("");
      }
      // Unconditional and by BOTH possible keys: convId is the real id in the
      // normal case; null only matters if creating the conversation itself
      // failed above (convId never got reassigned), so the placeholder must
      // still be released or that chat's input would stay stuck disabled.
      setSendingIds((prev) => {
        const next = new Set(prev);
        next.delete(convId);
        next.delete(null);
        return next;
      });
      // The backend auto-titles a new chat from its first message, so reload the
      // list to replace "New chat" with the real title in the sidebar.
      api.listConversations().then(setConversations).catch(() => {});
    }
  }

  // Derived value — not state. It's computed from state on every render, so it
  // can never fall out of sync. Only store in state what can't be derived.
  const selected = conversations.find((c) => c.id === selectedId) || null;
  const userInitial = (user.display_name || user.email || "?").charAt(0).toUpperCase();
  const conversationToDelete = conversations.find((c) => c.id === confirmDeleteId) || null;

  // A floating toast, not an inline banner: it used to sit at the TOP of the
  // scrollable message list, so on any chat with enough history to scroll,
  // it was off-screen the moment you were reading recent messages. `fixed`
  // positioning anchors it to the viewport corner instead — always visible,
  // regardless of scroll position or which screen (chat vs. home) is showing.
  // Rendered once, below, rather than once per screen.
  const errorToast = error && (
    <div className="fixed right-6 bottom-6 z-50 flex max-w-sm items-start gap-3 rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-600 shadow-lg ring-1 ring-red-200 dark:bg-ink-900 dark:text-red-400 dark:ring-red-500/30">
      <span className="flex-1">{error}</span>
      <button
        onClick={() => setError("")}
        aria-label="Dismiss error"
        className="flex-none rounded-md p-0.5 text-red-500 transition hover:bg-red-100 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-500/20"
      >
        <IconClose width={14} height={14} />
      </button>
    </div>
  );

  // Same "rendered once, fixed position" reasoning as errorToast — a modal
  // needs to sit above everything regardless of which screen is showing.
  const deleteConfirmModal = conversationToDelete && (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 px-4"
      onClick={() => setConfirmDeleteId(null)}
    >
      <div
        // Stop the overlay's onClick (which closes on any outside click) from
        // also firing when the click actually landed on the dialog itself.
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-5 shadow-xl dark:border-ink-700 dark:bg-ink-900"
      >
        <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          Delete this conversation?
        </h3>
        <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
          "{conversationToDelete.title}" will be permanently deleted. This cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={() => setConfirmDeleteId(null)}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-zinc-600 transition hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-ink-800"
          >
            Cancel
          </button>
          <button
            onClick={confirmDelete}
            className="rounded-lg bg-red-500 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-red-600"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );

  return (
    // Desktop/tablet: a real grid column for the sidebar — collapsing animates
    // it down to a 56px rail, never to zero, so the toggle/new-chat/theme/logout
    // icons stay reachable (ChatGPT/Claude style).
    // Mobile: no grid column at all. The sidebar becomes a fixed overlay drawer
    // (below) so the chat gets the FULL screen instead of sharing it with a
    // sidebar there isn't room for.
    <div
      className={
        "h-screen relative " +
        (isMobile
          ? ""
          : "grid " + (isResizing ? "" : "transition-[grid-template-columns] duration-200 ease-out"))
      }
      style={
        isMobile
          ? undefined
          : { gridTemplateColumns: collapsed ? "56px 1fr" : `${sidebarWidth}px 1fr` }
      }
    >
      {/* Backdrop: dims the chat and closes the drawer on tap. Mobile only —
          on desktop the sidebar is never an overlay, so there's nothing to dim. */}
      {isMobile && mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <div
        className={
          isMobile
            ? "fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] transition-transform duration-200 ease-out " +
              (mobileOpen ? "translate-x-0" : "-translate-x-full")
            : undefined
        }
      >
        <Sidebar
          conversations={conversations}
          selectedId={selectedId}
          onSelect={(id) => {
            switchToConversation(id);
            if (isMobile) setMobileOpen(false); // picked a chat -> get out of the way
          }}
          onNewChat={async () => {
            await handleNewChat();
            if (isMobile) setMobileOpen(false);
          }}
          onDelete={handleDelete}
          // The rail (collapsed-but-visible) is a desktop-only concept — on
          // mobile the drawer is either fully open or fully off-screen, so it
          // always shows its full contents while open.
          collapsed={isMobile ? false : collapsed}
          onToggle={handleToggleSidebar}
          theme={theme}
          onToggleTheme={onToggleTheme}
          user={user}
          onLogout={onLogout}
        />
      </div>

      {/* Drag handle: an absolutely-positioned strip straddling the sidebar/
          main boundary, not a real grid column — a grid column would force a
          layout change of its own just to hold a 6px hit target. Positioned
          via `left: sidebarWidth` so it always sits exactly on the boundary.
          Desktop + expanded only: collapsed is a fixed 56px rail (nothing to
          resize), and mobile's sidebar is an overlay drawer, not a column. */}
      {!isMobile && !collapsed && (
        <div
          onMouseDown={handleResizeStart}
          title="Drag to resize sidebar"
          className="absolute top-0 bottom-0 z-20 w-1.5 -translate-x-1/2 cursor-col-resize touch-none select-none"
          style={{ left: sidebarWidth }}
        >
          <div className="mx-auto h-full w-px bg-transparent transition-colors hover:bg-brand-500/60" />
        </div>
      )}

      {/* h-screen directly on main (not just min-h-0) is the real fix: a grid/flex
          item's height is normally set by its TRACK, but this app's outer grid
          only exists in desktop mode (mobile has no grid/flex context at all,
          since the sidebar becomes a `fixed` overlay) — so main had nothing
          reliably constraining its height in either mode. An explicit height
          works regardless of what the parent's layout mode is doing. Without
          it, main grows to fit its ENTIRE content (the whole message history),
          the page itself becomes that tall, and the browser scrolls the page —
          which is what made a freshly opened chat visibly scroll from the very
          top down to the bottom, instead of the inner .overflow-y-auto pane
          scrolling on its own while everything else stays put. min-h-0 still
          matters too: it's what lets this now-fixed-height box actually shrink
          its children instead of fighting them via the default min-height:auto. */}
      <main className="flex h-screen min-h-0 min-w-0 flex-col overflow-hidden">
        <header className="flex flex-none items-center gap-2 border-b border-zinc-200 bg-white px-4 py-2.5 dark:border-ink-800 dark:bg-ink-900">
          {/* On desktop the rail's own toggle is always visible, so a second one
              here would be the exact duplicate we removed earlier. On mobile the
              drawer can be fully hidden, so this is the ONLY way back in. */}
          {isMobile && (
            <button
              onClick={handleToggleSidebar}
              aria-label={mobileOpen ? "Close sidebar" : "Open sidebar"}
              title={mobileOpen ? "Close sidebar" : "Open sidebar"}
              className="grid h-8 w-8 flex-none place-items-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-ink-800 dark:hover:text-zinc-100"
            >
              <IconSidebar />
            </button>
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-medium">
            {selected ? selected.title : "WebsiteOS"}
          </span>
        </header>

        {selected ? (
          <>
            <div className="flex-1 overflow-y-auto px-4 py-6 md:px-6 md:py-8">
              <MessageList
                messages={messages}
                loading={loadingMessages}
                streamingText={streamingText}
                streamingSources={streamingSources}
                status={status}
                // Only show the "thinking…" bubble if THIS chat is one of the
                // ones currently generating — other chats generating in the
                // background don't affect what renders here.
                thinking={sendingIds.has(selectedId)}
                userInitial={userInitial}
                conversationId={selectedId}
              />
            </div>
            <div className="flex-none px-4 pt-3 pb-4 md:px-6 md:pb-6">
              {/* Disabled only while THIS specific chat is mid-send — a different
                  chat generating in the background doesn't block this one. */}
              <ChatInput onSend={handleSend} disabled={sendingIds.has(selectedId)} />
            </div>
          </>
        ) : (
          // Home screen: branding with the composer right beneath it. Sending from
          // here creates a conversation automatically (see handleSend).
          <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 pb-12 md:px-6">
            <div className="flex flex-col items-center gap-3 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 text-lg font-bold text-white shadow-lg shadow-brand-500/20">
                W
              </span>
              <h2 className="text-2xl font-semibold tracking-tight">
                What do you want to know?
              </h2>
              <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
                Ask anything about your indexed sites — a new chat starts automatically.
              </p>
            </div>

            <div className="w-full max-w-3xl">
              {/* selectedId is null here (home screen) — same lock key handleSend
                  uses for "a new chat is being created but has no id yet". */}
              <ChatInput onSend={handleSend} disabled={sendingIds.has(null)} />
            </div>
          </div>
        )}
      </main>

      {/* Rendered once here rather than per-screen — fixed positioning means
          its place in the DOM doesn't affect where it appears on screen. */}
      {errorToast}
      {deleteConfirmModal}
    </div>
  );
}
