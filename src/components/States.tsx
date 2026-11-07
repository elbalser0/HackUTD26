import type { ReactNode } from "react";
import { ApiError } from "../api";

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="state">
      Loading {what}…
    </p>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const e = error instanceof ApiError ? error : null;
  const unreachable = e?.status === 0 || (e?.status ?? 0) >= 502;
  return (
    <div role="alert" className="state state-error">
      <strong>
        {unreachable
          ? "Backend unavailable."
          : e?.status === 404
            ? "Not found."
            : "Could not load."}
      </strong>{" "}
      {(e?.message ?? "Unexpected error").replace(/\.?$/, ".")} Nothing here
      should be read as “no changes” — the data could not be fetched.
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Notice({
  tone,
  children,
}: {
  tone: "warn" | "info";
  children: ReactNode;
}) {
  return (
    <div role="note" className={`notice notice-${tone}`}>
      {children}
    </div>
  );
}

export const BYPASS_NOTE =
  "This warning only appears on the approved path (the apply wrapper). Running terraform directly bypasses it. The UI cannot execute, approve, or block anything.";
