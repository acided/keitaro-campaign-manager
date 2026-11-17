import { useEffect, useState } from "react";
import { CreatePage } from "./CreatePage";
import { EditorPage } from "./EditorPage";

// Two pages, so a hash is all the routing we need: #/new or #/campaigns/123
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const match = hash.match(/^#\/campaigns(?:\/(\d+))?/);
  if (match) return { page: "editor" as const, campaignId: match[1] ? Number(match[1]) : null };
  return { page: "new" as const, campaignId: null };
}

export function openCampaign(id: number | null) {
  window.location.hash = id === null ? "#/campaigns" : `#/campaigns/${id}`;
}

// index.html sets the initial theme; this only flips and remembers it.
function useTheme() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("theme", theme);
    } catch {
      // storage blocked: the choice just is not remembered
    }
  }, [theme]);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")] as const;
}

export function App() {
  const route = useHashRoute();
  const [theme, toggleTheme] = useTheme();
  return (
    <>
      <header>
        <strong>Keitaro campaign manager</strong>
        <nav>
          <a href="#/new" className={route.page === "new" ? "current" : ""}>
            New campaign
          </a>
          <a href="#/campaigns" className={route.page === "editor" ? "current" : ""}>
            Editor
          </a>
        </nav>
        <button className="theme" onClick={toggleTheme}>
          {theme === "dark" ? "☀ Light" : "☾ Dark"}
        </button>
      </header>
      <main>
        {route.page === "new" ? <CreatePage /> : <EditorPage campaignId={route.campaignId} />}
      </main>
    </>
  );
}
