/**
 * React wiring for Google sign-in. Firebase itself lives in ../auth.ts.
 *
 * When sign-in is configured, the app sits behind a full sign-in page
 * (<AuthGate>). The only way past it without Google is the shared-token admin
 * fallback, kept for when Google sign-in is unreachable (e.g. venue Wi-Fi).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { setTokenProvider } from "../api";
import { AuthContext, currentClient, none, useAuth } from "../auth";
import type { AuthState, AuthUser } from "../auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => currentClient(), []);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!client) return;
    setTokenProvider(() => client.getIdToken());
    const unsub = client.onChange((u) => {
      setUser(u);
      setReady(true);
    });
    return () => {
      unsub();
      setTokenProvider(null);
    };
  }, [client]);
  const value = useMemo<AuthState>(
    () =>
      client
        ? {
            configured: true,
            ready,
            user,
            signIn: () => client.signIn(),
            signOut: () => client.signOut(),
            getIdToken: () => client.getIdToken(),
          }
        : none,
    [client, ready, user],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function signInMessage(e: unknown): string {
  const m = e instanceof Error ? e.message : "";
  if (/popup-closed|cancelled-popup/i.test(m)) return "Sign-in was cancelled.";
  if (/popup-blocked/i.test(m)) return "Your browser blocked the Google popup. Allow popups for this site and try again.";
  if (/network/i.test(m)) return "Couldn't reach Google. Check the connection, or use offline admin access below.";
  return "Sign-in failed. Try again.";
}

/** Google's "G" mark, per Google's sign-in button branding. */
function GoogleMark() {
  return (
    <svg className="gmark" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export function GoogleButton({ label = "Sign in with Google" }: { label?: string }) {
  const { signIn } = useAuth();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // signIn() is called straight from the click so the browser allows the popup.
  const start = () => {
    setErr("");
    setBusy(true);
    signIn()
      .catch((e: unknown) => setErr(signInMessage(e)))
      .finally(() => setBusy(false));
  };
  return (
    <div className="gbtn-wrap">
      <button className="gbtn" onClick={start} disabled={busy}>
        <GoogleMark />
        <span>{busy ? "Waiting for Google…" : label}</span>
      </button>
      {err && (
        <p role="alert" className="bad">
          {err}
        </p>
      )}
    </div>
  );
}

function SignInPage({ onOffline }: { onOffline: () => void }) {
  return (
    <div className="signin-page">
      <section className="signin-card" aria-labelledby="signin-title">
        <img className="signin-logo" src="/argus-logo.svg" alt="Argus" />
        <h1 id="signin-title">
          Manual changes,
          <br />
          <span>before the next apply.</span>
        </h1>
        <p className="lede">
          Sign in to see emergency changes the scanner found, explain the ones
          you made, and review what the next Terraform apply would undo.
        </p>
        <GoogleButton />
        <ul className="signin-points">
          <li>Explanations you save are linked to your verified Google account.</li>
          <li>That shows who submitted an explanation, never who made the console change.</li>
          <li>You stay signed in until you close this tab.</li>
        </ul>
        <button className="linkish" onClick={onOffline}>
          Google sign-in unavailable? Admin offline access (shared token)
        </button>
      </section>
    </div>
  );
}

/** Blocks the app behind the sign-in page when Firebase sign-in is configured. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { configured, ready, user } = useAuth();
  const [offline, setOffline] = useState(false);
  if (!configured || user || offline) return <>{children}</>;
  if (!ready)
    return (
      <div className="signin-page">
        <p role="status" className="signin-checking">
          Checking sign-in…
        </p>
      </div>
    );
  return (
    <SignInPage
      onOffline={() => {
        window.location.hash = "#/admin";
        setOffline(true);
      }}
    />
  );
}

function initials(u: AuthUser): string {
  const src = (u.name || u.email).trim();
  const parts = src.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

/**
 * Header account area. One button (photo, name, email) opens a small menu with
 * Sign out. The menu closes on a second click, Escape, or a click outside it.
 */
export function AccountBar() {
  const { configured, user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const firstItem = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    firstItem.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  if (!configured) return null;
  if (!user)
    return (
      <div className="account account-out">
        <span className="account-state">Not signed in · offline admin access</span>
        <GoogleButton label="Sign in" />
      </div>
    );
  return (
    <div className="account" ref={root}>
      <button
        ref={trigger}
        className="account-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.email}`}
        onClick={() => setOpen((o) => !o)}
      >
        {user.photoUrl ? (
          <img className="avatar" src={user.photoUrl} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span className="avatar" aria-hidden="true">
            {initials(user)}
          </span>
        )}
        <span className="account-who">
          <strong>{user.name || user.email}</strong>
          <small>{user.email}</small>
        </span>
        <span className="account-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div className="account-menu" role="menu">
          <button
            ref={firstItem}
            role="menuitem"
            className="btn"
            onClick={() => {
              setOpen(false);
              void signOut();
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
