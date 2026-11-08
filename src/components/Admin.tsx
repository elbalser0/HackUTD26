import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../api";
import type { AdminEvent, AdminFilters, RunOutcome } from "../api";
import { useAuth } from "../auth";
import { formatDetected } from "../format";
import { useAsync } from "../useAsync";
import { ErrorState, Loading, Notice } from "./States";

type Denied =
  | "rejected"
  | "unconfigured"
  | "not_admin"
  | "email_unverified"
  | null;

/** How the admin view authenticates: Google sign-in (fresh ID token per call) or the shared fallback token. */
type Cred = { kind: "google"; email: string } | { kind: "shared"; token: string };

/**
 * R9 admin area. A shared token is held in this component's React state only:
 * never in the URL, localStorage or sessionStorage. A reload asks again. With
 * Google sign-in, a fresh Firebase ID token is fetched for every request and
 * never stored by this app. The server enforces access; this gate only decides
 * which credential to send.
 */
export function AdminArea({ path }: { path: string }) {
  const auth = useAuth();
  const [chosen, setCred] = useState<Cred | null>(null);
  const [lastKind, setLastKind] = useState<Cred["kind"]>("shared");
  const [denied, setDenied] = useState<Denied>(null);
  const timeline = path.match(/^\/admin\/records\/([^/]+)$/);

  // A Google unlock belongs to the account that chose it: signing out, or a
  // different account signing in, locks the view (derived, no effect needed).
  const cred: Cred | null =
    chosen?.kind === "google" && chosen.email !== auth.user?.email ? null : chosen;

  if (cred === null) {
    return (
      <TokenGate
        denied={denied}
        deniedKind={lastKind}
        onCred={(c) => {
          setDenied(null);
          setLastKind(c.kind);
          setCred(c);
        }}
      />
    );
  }
  const getToken = async (): Promise<string> => {
    if (cred.kind === "shared") return cred.token;
    const t = await auth.getIdToken();
    if (!t) throw new ApiError("Not signed in", 401, "sign_in_required");
    return t;
  };
  const credKey = cred.kind === "shared" ? "shared" : `google:${cred.email}`;
  const onDenied = (code: Exclude<Denied, null>) => {
    setCred(null);
    setDenied(code);
  };
  const lock = () => {
    setCred(null);
    setDenied(null);
  };
  return timeline ? (
    <TimelineView
      key={timeline[1]}
      getToken={getToken}
      credKey={credKey}
      id={decodeURIComponent(timeline[1])}
      onDenied={onDenied}
      onLock={lock}
    />
  ) : (
    <LogView getToken={getToken} credKey={credKey} onDenied={onDenied} onLock={lock} />
  );
}

function TokenGate({
  denied,
  deniedKind,
  onCred,
}: {
  denied: Denied;
  deniedKind: Cred["kind"];
  onCred: (c: Cred) => void;
}) {
  const auth = useAuth();
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) onCred({ kind: "shared", token: value.trim() });
    setValue("");
  };
  const tokenForm = (
    <form className="form" onSubmit={submit}>
      <label>
        Admin token
        <input
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <button className="btn primary" type="submit">
        Unlock
      </button>
    </form>
  );
  return (
    <section className="detail">
      <div className="eyebrow">ADMIN</div>
      <h1>
        Team-wide history,
        <br />
        <span>for authorized admins.</span>
      </h1>
      <p className="lede">
        {auth.configured
          ? "Continue with an admin Google account, or use the shared admin token as an offline fallback. "
          : "Enter the admin token to read the log. "}
        Credentials are sent only as a request header, kept in this tab&rsquo;s
        memory, and forgotten on reload or sign-out. The server decides who may
        read; this page cannot grant access.
      </p>
      {denied === "rejected" && (
        <div role="alert" className="state state-error">
          {deniedKind === "google" ? (
            <>
              <strong>Google sign-in rejected or expired.</strong> Sign in
              again and retry. Nothing was loaded.
            </>
          ) : (
            <>
              <strong>Token rejected.</strong> The server did not accept it.
              Check it and try again. Nothing was loaded.
            </>
          )}
        </div>
      )}
      {denied === "not_admin" && (
        <div role="alert" className="state state-error">
          <strong>This Google account is not an admin.</strong> The server
          accepted the sign-in but this email is not on its admin list. Nothing
          was loaded.
        </div>
      )}
      {denied === "email_unverified" && (
        <div role="alert" className="state state-error">
          <strong>This Google account&rsquo;s email isn&rsquo;t verified.</strong>{" "}
          The server refuses unverified accounts. Nothing was loaded.
        </div>
      )}
      {denied === "unconfigured" && (
        <div role="alert" className="state state-error">
          <strong>Admin access is not configured on the server.</strong> No
          admin token is set there, so it refuses all admin requests. Nothing
          was loaded.
        </div>
      )}
      {auth.configured ? (
        <>
          <div className="form">
            {auth.user ? (
              <button
                className="btn primary"
                onClick={() => auth.user && onCred({ kind: "google", email: auth.user.email })}
              >
                Continue as {auth.user.email}
              </button>
            ) : (
              <button className="btn primary" onClick={() => void auth.signIn()}>
                Sign in with Google
              </button>
            )}
          </div>
          <h3>Offline fallback: shared admin token</h3>
          <p className="meta">
            For when Google sign-in is unavailable. It shows that an admin read
            the log, not which admin.
          </p>
          {tokenForm}
        </>
      ) : (
        tokenForm
      )}
    </section>
  );
}

const OUTCOMES: RunOutcome[] = [
  "unknown",
  "failed",
  "cancelled",
  "kept",
  "deferred",
  "no_changes",
  "applied_no_warnings",
  "reverted_applied",
  "override_applied",
  "unverified_bypass_applied",
  "aborted_plan_changed",
];

const utc = (v: string) => (v.length === 16 ? `${v}:00Z` : `${v}Z`);

function useDeny(
  s: { state: string; error?: unknown },
  onDenied: (c: Exclude<Denied, null>) => void,
) {
  const e = s.state === "error" && s.error instanceof ApiError ? s.error : null;
  const status = e?.status;
  useEffect(() => {
    if (status === 401) onDenied("rejected");
    if (status === 403)
      onDenied(
        e?.code === "not_admin"
          ? "not_admin"
          : e?.code === "email_unverified"
            ? "email_unverified"
            : "unconfigured",
      );
    // eslint-disable-next-line
  }, [status]);
}

function LogView({
  getToken,
  credKey,
  onDenied,
  onLock,
}: {
  getToken: () => Promise<string>;
  credKey: string;
  onDenied: (c: Exclude<Denied, null>) => void;
  onLock: () => void;
}) {
  const [draft, setDraft] = useState({
    engineer: "",
    resource: "",
    outcome: "",
    since: "",
    until: "",
  });
  const [applied, setApplied] = useState<AdminFilters>({});
  const { s, reload } = useAsync(
    () => getToken().then((t) => api.adminLog(t, applied)),
    [credKey, applied],
  );
  useDeny(s, onDenied);
  const set = (k: keyof typeof draft) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [k]: e.target.value });
  const apply = (e: FormEvent) => {
    e.preventDefault();
    const f: AdminFilters = {};
    if (draft.engineer.trim()) f.engineer = draft.engineer.trim();
    if (draft.resource.trim()) f.resource = draft.resource.trim();
    if (draft.outcome) f.outcome = draft.outcome as RunOutcome;
    if (draft.since) f.since = utc(draft.since);
    if (draft.until) f.until = utc(draft.until);
    setApplied(f);
  };
  const denied =
    s.state === "error" &&
    s.error instanceof ApiError &&
    (s.error.status === 401 || s.error.status === 403);
  return (
    <section className="detail">
      <div className="eyebrow">ADMIN LOG</div>
      <h1>
        Who did what,
        <br />
        <span>across the team.</span>
      </h1>
      <div className="row">
        <button className="btn" onClick={onLock}>
          Lock admin view
        </button>
      </div>
      <form className="form" onSubmit={apply} aria-label="Filters">
        <label>
          Engineer
          <input value={draft.engineer} onChange={set("engineer")} />
        </label>
        <label>
          Resource
          <input
            value={draft.resource}
            onChange={set("resource")}
            placeholder="digitalocean_firewall.demo"
          />
        </label>
        <label>
          Outcome
          <select value={draft.outcome} onChange={set("outcome")}>
            <option value="">Any</option>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <label>
          From (UTC)
          <input
            type="datetime-local"
            value={draft.since}
            onChange={set("since")}
          />
        </label>
        <label>
          To (UTC)
          <input
            type="datetime-local"
            value={draft.until}
            onChange={set("until")}
          />
        </label>
        <button className="btn primary" type="submit">
          Apply filters
        </button>
      </form>
      {s.state === "loading" && <Loading what="log" />}
      {s.state === "error" && !denied && (
        <ErrorState error={s.error} onRetry={reload} />
      )}
      {s.state === "ok" && (
        <>
          <p className="meta">
            Showing {s.data.events.length} of {s.data.totalMatching} matching
            events, newest first.
          </p>
          {s.data.events.length === 0 ? (
            <p className="state">
              No events match these filters. This does not prove nothing
              happened: only changes the tool captured are recorded.
            </p>
          ) : (
            <ul className="cards">
              {s.data.events.map((e, i) => (
                <EventRow key={i} e={e} />
              ))}
            </ul>
          )}
          <Limitations items={s.data.limitations} />
        </>
      )}
    </section>
  );
}

function TimelineView({
  getToken,
  credKey,
  id,
  onDenied,
  onLock,
}: {
  getToken: () => Promise<string>;
  credKey: string;
  id: string;
  onDenied: (c: Exclude<Denied, null>) => void;
  onLock: () => void;
}) {
  const { s, reload } = useAsync(
    () => getToken().then((t) => api.adminTimeline(t, id)),
    [credKey, id],
  );
  useDeny(s, onDenied);
  const denied =
    s.state === "error" &&
    s.error instanceof ApiError &&
    (s.error.status === 401 || s.error.status === 403);
  return (
    <section className="detail">
      <a href="#/admin">← Back to log</a>
      <div className="eyebrow">RECORD TIMELINE</div>
      <h1 className="resource">{id}</h1>
      <div className="row">
        <button className="btn" onClick={onLock}>
          Lock admin view
        </button>
      </div>
      {s.state === "loading" && <Loading what="timeline" />}
      {s.state === "error" && !denied && (
        <ErrorState error={s.error} onRetry={reload} />
      )}
      {s.state === "ok" && (
        <>
          {s.data.gaps.length > 0 && (
            <section
              aria-label="Gaps in the evidence"
              className="notice notice-warn"
            >
              <strong>Gaps in the evidence</strong>
              <ul>
                {s.data.gaps.map((g, i) => (
                  <li key={i}>{g.message}</li>
                ))}
              </ul>
            </section>
          )}
          <p className="meta">Oldest first.</p>
          <ul className="cards">
            {s.data.events.map((e, i) => (
              <EventRow key={i} e={e} timeline />
            ))}
          </ul>
          <Limitations items={s.data.limitations} />
        </>
      )}
    </section>
  );
}

const TYPE_LABEL: Record<AdminEvent["type"], string> = {
  change_detected: "change detected",
  explained: "explained",
  decision: "decision",
  review: "wrapper review",
  run_started: "apply started",
  run_finished: "apply finished",
  run_unfinished: "apply UNFINISHED",
  resolved: "resolved",
};

function EventRow({ e, timeline }: { e: AdminEvent; timeline?: boolean }) {
  const who =
    e.actor === null
      ? "recorded by the tool (system)"
      : `${e.actor} · ${e.actorAssurance}`;
  return (
    <li aria-label={`${TYPE_LABEL[e.type]} event`} className="card panel">
      <div className="card-top">
        <strong>{TYPE_LABEL[e.type]}</strong>
        <span className="tag">{formatDetected(e.at)}</span>
      </div>
      <div className="meta">{who}</div>
      {e.resourceAddresses.length > 0 && (
        <div className="meta">
          <code>{e.resourceAddresses.join(", ")}</code>
        </div>
      )}
      {e.detail && <p className="msg">{e.detail}</p>}
      {e.outcome && (
        <div className={e.outcome === "unknown" ? "meta bad" : "meta"}>
          outcome: {e.outcome}
          {e.outcome === "unknown" &&
            " — no completion was recorded. Unknown is not the same as failed, and never means success."}
        </div>
      )}
      {e.planFingerprint && (
        <div className="meta">reviewed plan: {e.planFingerprint}</div>
      )}
      {!timeline &&
        e.recordIds.map((r) => (
          <a
            key={r}
            href={`#/admin/records/${encodeURIComponent(r)}`}
            className="nav-link"
          >
            Timeline for {r}
          </a>
        ))}
    </li>
  );
}

function Limitations({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Notice tone="info">
      <strong>What this view cannot tell you</strong>
      <ul>
        {items.map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
    </Notice>
  );
}
