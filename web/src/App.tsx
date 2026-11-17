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

export function App() {
  const route = useHashRoute();
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
      </header>
      <main>
        {route.page === "new" ? <CreatePage /> : <EditorPage campaignId={route.campaignId} />}
      </main>
    </>
  );
}
