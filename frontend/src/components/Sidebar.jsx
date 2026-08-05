// --- Imports: local ---
import { IconLogout, IconMoon, IconPlus, IconSidebar, IconSun } from "./Icons";

const ICON_BTN =
  "grid h-8 w-8 flex-none place-items-center rounded-lg text-zinc-500 transition " +
  "hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-ink-800 dark:hover:text-zinc-100";

// Presentational component: holds NO state of its own. Everything it shows
// arrives as props, and everything it does is a callback the parent passed in.
//
// Collapsed, it becomes a narrow icon rail (like ChatGPT/Claude) rather than
// disappearing — so the toggle and "new chat" stay reachable without a second
// button living in the main header.
export default function Sidebar({
  conversations,
  selectedId,
  onSelect,
  onNewChat,
  onDelete,
  collapsed,
  onToggle,
  theme,
  onToggleTheme,
  user,
  onLogout,
  sites,
  selectedSites,
  onToggleSite,
}) {
  return (
    // h-full is the fix: this element used to be a DIRECT grid child, and CSS
    // Grid auto-stretches direct children to fill the row height with no height
    // rule needed. Once it's wrapped in a positioning <div> (for the mobile
    // drawer), it's a grandchild instead — stretch no longer reaches it, so it
    // must ask for 100% height itself. Works in both places: the grid track
    // (desktop) and the fixed inset-y-0 drawer wrapper (mobile) both give their
    // child a definite height for h-full to resolve against.
    <aside className="h-full min-w-0 overflow-hidden border-r border-zinc-200 bg-white dark:border-ink-800 dark:bg-ink-900">
      {/* w-full (not a fixed width): the contents reflow as the grid track
          animates, so collapsing looks like a smooth slide rather than a clip. */}
      <div
        className={
          "flex h-full w-full flex-col " +
          (collapsed ? "items-center gap-2 p-2" : "gap-3 p-3")
        }
      >
        {/* --- head: brand + toggle --- */}
        <div
          className={
            "flex flex-none items-center " +
            (collapsed ? "justify-center" : "justify-between gap-2 pl-1")
          }
        >
          {!collapsed && (
            <div className="flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 text-[13px] font-bold text-white">
                W
              </span>
              <span className="font-semibold tracking-tight">WebsiteOS</span>
            </div>
          )}
          <button
            className={ICON_BTN}
            onClick={onToggle}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <IconSidebar />
          </button>
        </div>

        {/* --- new chat: full button when open, icon-only on the rail --- */}
        {collapsed ? (
          <button className={ICON_BTN} onClick={onNewChat} title="New chat" aria-label="New chat">
            <IconPlus />
          </button>
        ) : (
          <button
            onClick={onNewChat}
            className="flex flex-none items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2.5 text-sm font-medium transition hover:border-zinc-300 hover:bg-zinc-100 dark:border-ink-700 dark:bg-ink-850 dark:hover:border-ink-600 dark:hover:bg-ink-800"
          >
            <IconPlus width={16} height={16} />
            New chat
          </button>
        )}

        {/* --- site picker: which sources to search --- */}
        {!collapsed && sites.length > 0 && (
          <div className="flex-none">
            <div className="mb-1.5 flex items-baseline justify-between px-1">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                Sources
              </span>
              {/* Empty selection means "search everything" — say so, otherwise
                  it reads as a broken empty state rather than a default. */}
              <span className="text-[11px] text-zinc-400 dark:text-zinc-500">
                {selectedSites.length === 0 ? "All" : `${selectedSites.length} selected`}
              </span>
            </div>

            <div className="flex flex-col gap-0.5">
              {sites.map((site) => (
                <label
                  key={site.id}
                  title={site.description}
                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-zinc-600 transition hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-ink-850"
                >
                  <input
                    type="checkbox"
                    checked={selectedSites.includes(site.id)}
                    onChange={() => onToggleSite(site.id)}
                    className="h-3.5 w-3.5 flex-none rounded border-zinc-300 text-brand-500 focus:ring-brand-500 dark:border-ink-600 dark:bg-ink-850"
                  />
                  <span className="min-w-0 truncate">{site.label}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* --- conversation list: only when expanded --- */}
        {!collapsed && (
          // min-h-0 for the same reason as ChatApp's <main>: a flex-1 item still
          // defaults to min-height:auto, so with enough conversations this would
          // otherwise grow past its allotted space instead of scrolling within it.
          <nav className="-mx-1 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-1">
            {conversations.length === 0 && (
              <p className="px-2 py-1.5 text-sm text-zinc-400 dark:text-zinc-500">
                No conversations yet.
              </p>
            )}

            {/* .map() turns data into elements. `key` must be a stable unique id —
                it's how React tracks which item is which across re-renders. */}
            {conversations.map((conv) => {
              const active = conv.id === selectedId;
              return (
                <div
                  key={conv.id}
                  className={
                    "group flex items-center rounded-lg transition " +
                    (active ? "bg-brand-500/10" : "hover:bg-zinc-100 dark:hover:bg-ink-850")
                  }
                >
                  <button
                    onClick={() => onSelect(conv.id)}
                    className={
                      "min-w-0 flex-1 truncate px-2.5 py-2 text-left text-sm transition " +
                      (active
                        ? "font-medium text-zinc-900 dark:text-zinc-100"
                        : "text-zinc-500 dark:text-zinc-400")
                    }
                  >
                    {conv.title}
                  </button>
                  <button
                    onClick={() => onDelete(conv.id)}
                    aria-label={`Delete ${conv.title}`}
                    className="flex-none rounded-md px-2.5 py-1.5 text-zinc-400 opacity-0 transition group-hover:opacity-100 hover:text-red-500 focus-visible:opacity-100 dark:text-zinc-500"
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </nav>
        )}

        {/* Pushes the footer down when the conversation list isn't there to do it */}
        {collapsed && <div className="flex-1" />}

        {/* --- footer: side by side when open, stacked on the rail --- */}
        <div
          className={
            "flex flex-none border-t border-zinc-200 pt-3 dark:border-ink-800 " +
            (collapsed ? "flex-col items-center gap-1" : "items-center gap-1")
          }
        >
          {!collapsed && (
            <span className="min-w-0 flex-1 truncate pl-1 text-[13px] text-zinc-500 dark:text-zinc-400">
              {user.display_name || user.email}
            </span>
          )}
          <button
            className={ICON_BTN}
            onClick={onToggleTheme}
            title={theme === "dark" ? "Light mode" : "Dark mode"}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
          <button className={ICON_BTN} onClick={onLogout} title="Log out" aria-label="Log out">
            <IconLogout />
          </button>
        </div>
      </div>
    </aside>
  );
}
