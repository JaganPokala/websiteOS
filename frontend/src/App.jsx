// --- Imports: React ---
import { useEffect, useState } from "react";

// --- Imports: local ---
import * as api from "./lib/api";
import AuthScreen from "./screens/AuthScreen";
import ChatApp from "./screens/ChatApp";

// App is the root component: it owns "who is logged in" and decides which screen
// to show. Keeping that state HERE (not inside AuthScreen) is called "lifting
// state up" — the whole app needs to know, so the shared parent holds it.
export default function App() {
  const [user, setUser] = useState(null); // null = not logged in
  const [loading, setLoading] = useState(true); // true until we've checked

  // Theme. The lazy initialiser (a function passed to useState) runs only on the
  // first render, so we read localStorage once instead of on every render.
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "dark");

  // Every CSS rule keys off [data-theme] on <html>, so switching themes is just
  // swapping one attribute — no component needs to know about colours.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  // Verify whoever the stored token belongs to. Called on first load AND right
  // after a successful login/signup.
  async function loadUser() {
    if (!api.getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.me()); // token is valid -> we get the profile back
    } catch {
      api.clearToken(); // expired or tampered -> drop it and show the login screen
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  // Run once after the first render. The [] means "no dependencies, don't re-run".
  // This is where data-loading lives in React.
  useEffect(() => {
    loadUser();
  }, []);

  function handleLogout() {
    api.clearToken(); // remove the JWT from localStorage
    setUser(null); // state change -> React re-renders -> AuthScreen appears
  }

  // Conditional rendering: three possible screens, decided by state.
  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500 dark:text-zinc-400">
        Loading…
      </div>
    );

  // Not logged in -> show the auth screen, and hand it a callback so it can tell
  // us when login succeeded.
  if (!user) return <AuthScreen onAuthenticated={loadUser} />;

  // Logged in -> the full chat shell.
  return (
    <ChatApp
      user={user}
      onLogout={handleLogout}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  );
}
