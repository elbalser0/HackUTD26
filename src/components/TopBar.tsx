import { api } from "../api";
import { useAuth } from "../auth";
import { useAsync } from "../useAsync";
import { usingFixtures } from "../api";
import { AccountBar } from "./AuthProvider";
import { usePalette } from "../paletteContext";

const SHORTCUT =
  typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform)
    ? "⌘K"
    : "Ctrl K";

/**
 * Top bar. The persona comes from GET /api/me and only decides which links to
 * show; every route still enforces access on the server. If /api/me fails the
 * bar falls back to the employee view (no admin link), never to admin.
 */
export function TopBar() {
  const { user } = useAuth();
  const palette = usePalette();
  const { s } = useAsync(() => api.me(), [user?.email]);
  const admin = s.state === "ok" && s.data.role === "admin";
  return (
    <header className="top">
      <a className="brand" href="#/" aria-label="Argus home">
        <img src="/argus-logo.svg" alt="" />
      </a>
      <div className="top-right">
        {usingFixtures && (
          <span className="chip">DEV FIXTURE DATA, NOT A BACKEND</span>
        )}
        <button
          className="chip search-btn"
          aria-haspopup="dialog"
          onClick={() => palette.setOpen(true)}
        >
          Search records <span className="kbd">{SHORTCUT}</span>
        </button>
        {admin && (
          <a className="chip" href="#/admin">
            Admin
          </a>
        )}
        <AccountBar />
      </div>
    </header>
  );
}
