// --- Imports: React ---
import { useState } from "react";

// --- Imports: local ---
import * as api from "../lib/api";

// A component is just a function that returns what to show (JSX).
// `onAuthenticated` is a PROP — a function App passes down so this component can
// tell its parent "login worked". Data flows down, events flow up.
export default function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  const inputClass =
    "w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5 text-[15px] outline-none transition " +
    "placeholder:text-zinc-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 " +
    "dark:border-ink-700 dark:bg-ink-950 dark:placeholder:text-zinc-600";

  async function handleSubmit(e) {
    // Without this, the browser reloads the page on submit and wipes React state.
    e.preventDefault();
    setError("");
    setBusy(true); // disables the button so a double-click can't fire two requests

    try {
      const data = isSignup
        ? await api.signup(email, password, displayName)
        : await api.login(email, password);

      api.setToken(data.access_token); // -> localStorage, survives refresh
      onAuthenticated(); // tell App to re-check who's logged in
    } catch (err) {
      // Every failure from api.js arrives here as a thrown Error, so one catch
      // handles wrong password, duplicate email, and network failure alike.
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-ink-800 dark:bg-ink-900"
      >
        <div className="mb-7 flex items-center gap-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 text-[13px] font-bold text-white">
            W
          </span>
          <span className="font-semibold tracking-tight">WebsiteOS</span>
        </div>

        <h1 className="text-xl font-semibold tracking-tight">
          {isSignup ? "Create account" : "Welcome back"}
        </h1>
        <p className="mt-1 mb-6 text-sm text-zinc-500 dark:text-zinc-400">
          {isSignup ? "Sign up to start asking." : "Log in to continue."}
        </p>

        {/* `{cond && <jsx/>}` — React's usual way to render something conditionally */}
        {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </div>
        )}

        {isSignup && (
          <div className="mb-4">
            <label
              htmlFor="displayName"
              className="mb-1.5 block text-[13px] font-medium text-zinc-500 dark:text-zinc-400"
            >
              Name
            </label>
            <input
              id="displayName"
              className={inputClass}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Jagan"
            />
          </div>
        )}

        <div className="mb-4">
          <label
            htmlFor="email"
            className="mb-1.5 block text-[13px] font-medium text-zinc-500 dark:text-zinc-400"
          >
            Email
          </label>
          {/* A "controlled input": value comes FROM state, every keystroke writes
              back to state. State is the source of truth, not the DOM. */}
          <input
            id="email"
            type="email"
            required
            className={inputClass}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </div>

        <div className="mb-5">
          <label
            htmlFor="password"
            className="mb-1.5 block text-[13px] font-medium text-zinc-500 dark:text-zinc-400"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={isSignup ? 8 : undefined}
            className={inputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-brand-600 py-2.5 font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Please wait…" : isSignup ? "Create account" : "Log in"}
        </button>

        <p className="mt-5 text-center text-sm text-zinc-500 dark:text-zinc-400">
          {isSignup ? "Already have an account?" : "No account yet?"}{" "}
          <button
            type="button" // not "submit", or clicking it would submit the form
            onClick={() => {
              setMode(isSignup ? "login" : "signup");
              setError("");
            }}
            className="font-medium text-brand-500 hover:underline"
          >
            {isSignup ? "Log in" : "Sign up"}
          </button>
        </p>
      </form>
    </div>
  );
}
