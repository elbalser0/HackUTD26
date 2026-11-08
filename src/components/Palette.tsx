/**
 * Command palette (employee scope): records and the three filters, searched
 * client-side over the list the page already loaded. Type to filter, arrows to
 * move, Enter to open, Esc to close. Focus stays in the input (Tab is trapped)
 * and returns to whatever opened the palette.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { EmergencyRecord } from "../api";
import { allTermsIn, MAX_RECORDS, recordMatches, termsOf } from "../palette";
import { BUCKETS, bucketOf } from "../records";
import { Highlight } from "./PaletteParts";
import { metaFor, tagFor } from "../paletteRows";
import type { Bucket } from "../records";

type Row =
  | { kind: "record"; id: string; record: EmergencyRecord }
  | { kind: "filter"; id: string; bucket: Bucket; label: string };

export function Palette({
  records,
  onRecord,
  onFilter,
  onClose,
}: {
  records: EmergencyRecord[];
  onRecord: (r: EmergencyRecord) => void;
  onFilter: (b: Bucket) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const uid = useId();
  const [opener] = useState(() => document.activeElement as HTMLElement | null);

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
  const matched = useMemo(
    () => records.filter((r) => recordMatches(r, terms)),
    [records, terms],
  );
  const shown = matched.slice(0, MAX_RECORDS);
  const filters = BUCKETS.filter((b) => allTermsIn(b.label, terms)).map((b) => ({
    ...b,
    count: records.filter((r) => bucketOf(r) === b.id).length,
  }));
  const rows: Row[] = [
    ...shown.map((r): Row => ({ kind: "record", id: `${uid}-r-${r.id}`, record: r })),
    ...filters.map(
      (f): Row => ({
        kind: "filter",
        id: `${uid}-f-${f.id}`,
        bucket: f.id,
        label: `${f.label} · ${f.count}`,
      }),
    ),
  ];
  const at = rows.length ? Math.min(active, rows.length - 1) : -1;

  const activeId = rows[at]?.id ?? "";
  useEffect(() => {
    document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);

  const pick = (row: Row | undefined) => {
    if (!row) return;
    if (row.kind === "record") onRecord(row.record);
    else onFilter(row.bucket);
    onClose();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Tab") {
      e.preventDefault();
      input.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (rows.length === 0) return;
      const d = e.key === "ArrowDown" ? 1 : -1;
      setActive((at + d + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(rows[at]);
    }
  };

  const option = (row: Row, i: number, body: React.ReactNode) => (
    <div
      key={row.id}
      id={row.id}
      role="option"
      className="pal-row"
      aria-selected={i === at}
      onMouseDown={(e) => e.preventDefault()}
      onMouseMove={() => i !== at && setActive(i)}
      onClick={() => pick(row)}
    >
      {body}
    </div>
  );

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
            aria-label="Search records and filters"
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
        <div className="pal-list" id={`${uid}-list`} role="listbox" aria-label="Results" ref={list}>
          {rows.length === 0 && (
            <p className="pal-empty">
              No matches. This does not mean nothing changed: it only covers
              the records on this page.
            </p>
          )}
          {shown.length > 0 && (
            <div className="pal-group" role="group" aria-label="Records">
              <div className="pal-label">RECORDS · {matched.length}</div>
              {shown.map((r, i) => {
                const t = tagFor(r);
                return option(
                  rows[i],
                  i,
                  <>
                    <div className="grow">
                      <div className="t mono">
                        <Highlight text={r.resourceAddress} terms={terms} />
                      </div>
                      <div className="m">{metaFor(r)}</div>
                    </div>
                    <span className={`tag ${t.tone}`}>{t.label}</span>
                  </>,
                );
              })}
              {matched.length > shown.length && (
                <div className="pal-more">
                  Showing the first {shown.length}. Type more to narrow it.
                </div>
              )}
            </div>
          )}
          {filters.length > 0 && (
            <div className="pal-group" role="group" aria-label="Filters">
              <div className="pal-label">FILTERS</div>
              {filters.map((f, j) => {
                const i = shown.length + j;
                return option(
                  rows[i],
                  i,
                  <div className="grow">
                    <div className="t">
                      <Highlight text={f.label} terms={terms} /> · {f.count}
                    </div>
                  </div>,
                );
              })}
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
          <span style={{ marginLeft: "auto" }}>Records and filters</span>
        </div>
      </div>
    </div>
  );
}
