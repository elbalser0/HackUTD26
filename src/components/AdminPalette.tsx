/**
 * Command palette (admin scope): records, events and "Go to" pages. Records and
 * events are fetched when the palette opens (records from /api/records, events
 * from the first page of /api/admin/log) and searched client-side, so it only
 * covers what was loaded. Same keyboard behaviour as the employee palette.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { api } from "../api";
import type { AdminEvent, EmergencyRecord } from "../api";
import { EVENT_LABEL, shortUtc } from "../events";
import {
  allTermsIn,
  eventHash,
  eventMatches,
  GO_TO,
  MAX_EVENTS,
  MAX_RECORDS,
  recordMatches,
  termsOf,
} from "../palette";
import { useAsync } from "../useAsync";
import { Highlight } from "./PaletteParts";
import { metaFor, tagFor } from "../paletteRows";

type Row = { id: string; hash: string };

export function AdminPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const uid = useId();
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  const recs = useAsync(() => api.listRecords(), []);
  const evs = useAsync(() => api.adminEvents({}), []);

  useEffect(() => {
    input.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [onClose, opener]);

  const terms = useMemo(() => termsOf(query), [query]);
  const records: EmergencyRecord[] = recs.s.state === "ok" ? recs.s.data.records : [];
  const events: AdminEvent[] = evs.s.state === "ok" ? evs.s.data.events : [];
  const totalEvents = evs.s.state === "ok" ? evs.s.data.totalMatching : 0;
  const mRecords = records.filter((r) => recordMatches(r, terms));
  const mEvents = events.filter((e) => eventMatches(e, terms));
  const shownRecords = mRecords.slice(0, MAX_RECORDS);
  const shownEvents = mEvents.slice(0, MAX_EVENTS);
  const pages = GO_TO.filter((g) => allTermsIn(g.label, terms));

  const rows: Row[] = [
    ...shownRecords.map((r) => ({
      id: `${uid}-r-${r.id}`,
      hash: `#/admin/records/${encodeURIComponent(r.id)}`,
    })),
    ...shownEvents.map((e, i) => ({ id: `${uid}-e-${i}`, hash: eventHash(e) })),
    ...pages.map((g) => ({ id: `${uid}-g-${g.hash}`, hash: g.hash })),
  ];
  const at = rows.length ? Math.min(active, rows.length - 1) : -1;
  const activeId = rows[at]?.id ?? "";
  useEffect(() => {
    document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);

  const pick = (row: Row | undefined) => {
    if (!row) return;
    window.location.assign(row.hash);
    onClose();
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Tab") {
      e.preventDefault();
      input.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (rows.length === 0) return;
      setActive((at + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(rows[at]);
    }
  };
  const option = (i: number, body: React.ReactNode) => (
    <div
      key={rows[i].id}
      id={rows[i].id}
      role="option"
      className="pal-row"
      aria-selected={i === at}
      onMouseDown={(e) => e.preventDefault()}
      onMouseMove={() => i !== at && setActive(i)}
      onClick={() => pick(rows[i])}
    >
      {body}
    </div>
  );

  const loading = recs.s.state === "loading" || evs.s.state === "loading";
  const eventsOffset = shownRecords.length;
  const pagesOffset = eventsOffset + shownEvents.length;

  return (
    <div
      className="pal-backdrop"
      data-testid="palette-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="pal" role="dialog" aria-modal="true" aria-label="Search" onKeyDown={onKeyDown}>
        <div className="pal-in">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
          <input
            ref={input}
            role="combobox"
            aria-label="Search records, people and events"
            aria-expanded="true"
            aria-controls={`${uid}-list`}
            aria-activedescendant={rows[at]?.id}
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
          />
          <span className="kbd">esc</span>
        </div>
        <div className="pal-list" id={`${uid}-list`} role="listbox" aria-label="Results">
          {loading && <p className="pal-empty">Loading records and events…</p>}
          {recs.s.state === "error" && (
            <p className="pal-empty">Records could not be loaded. Pages still work.</p>
          )}
          {evs.s.state === "error" && (
            <p className="pal-empty">Events could not be loaded. Records and pages still work.</p>
          )}
          {!loading && rows.length === 0 && (
            <p className="pal-empty">
              No matches. This does not mean nothing happened: it only covers the loaded records
              and the latest {events.length} events.
            </p>
          )}
          {shownRecords.length > 0 && (
            <div className="pal-group" role="group" aria-label="Records">
              <div className="pal-label">RECORDS · {mRecords.length}</div>
              {shownRecords.map((r, i) => {
                const t = tagFor(r);
                return option(
                  i,
                  <>
                    <div className="grow">
                      <div className="t mono">
                        <Highlight text={r.resourceAddress} terms={terms} />
                      </div>
                      <div className="m">
                        {r.reporter ? (
                          <>
                            explained by <Highlight text={r.reporter} terms={terms} /> ·{" "}
                            {metaFor(r, false)}
                          </>
                        ) : (
                          metaFor(r)
                        )}
                      </div>
                    </div>
                    <span className={`tag ${t.tone}`}>{t.label}</span>
                  </>,
                );
              })}
              {mRecords.length > shownRecords.length && (
                <div className="pal-more">
                  Showing the first {shownRecords.length}. Type more to narrow it.
                </div>
              )}
            </div>
          )}
          {shownEvents.length > 0 && (
            <div className="pal-group" role="group" aria-label="Events">
              <div className="pal-label">EVENTS · {mEvents.length}</div>
              {shownEvents.map((e, i) =>
                option(
                  eventsOffset + i,
                  <div className="grow">
                    <div className="t">{EVENT_LABEL[e.type]}</div>
                    <div className="m">
                      {[
                        e.actor,
                        e.resourceAddresses[0],
                        e.detail ? `“${e.detail}”` : null,
                        shortUtc(e.at) + " UTC",
                      ]
                        .filter(Boolean)
                        .map((s, j, a) => (
                          <span key={j}>
                            <Highlight text={s as string} terms={terms} />
                            {j < a.length - 1 && " · "}
                          </span>
                        ))}
                    </div>
                  </div>,
                ),
              )}
              <div className="pal-more">
                Searched the latest {events.length} of {totalEvents} events.
                {mEvents.length > shownEvents.length && " Showing the first " + shownEvents.length + "."}
              </div>
            </div>
          )}
          {pages.length > 0 && (
            <div className="pal-group" role="group" aria-label="Go to">
              <div className="pal-label">GO TO</div>
              {pages.map((g, j) =>
                option(
                  pagesOffset + j,
                  <div className="grow">
                    <div className="t">
                      <Highlight text={g.label} terms={terms} />
                    </div>
                  </div>,
                ),
              )}
            </div>
          )}
        </div>
        <div className="pal-foot">
          <span>
            <span className="kbd">↑</span>
            <span className="kbd">↓</span>Navigate
          </span>
          <span>
            <span className="kbd">↵</span>Open
          </span>
          <span>
            <span className="kbd">esc</span>Close
          </span>
          <span style={{ marginLeft: "auto" }}>Records, people, events and pages</span>
        </div>
      </div>
    </div>
  );
}
