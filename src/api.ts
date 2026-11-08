/**
 * API client + wire mapping for docs/API.md (branch feat/break-glass-backend,
 * owned by Samuel). ALL wire knowledge lives here: snake_case JSON in,
 * camelCase domain objects out. Verified against the real backend.
 */
import { fixtureAdapter } from "./fixtures";

export type Intent = "unset" | "keep" | "revert" | "unsure" | "defer";
export type Resolution = "open" | "resolved";
export type CheckStatus = "current" | "stale" | "failed" | "unsupported";
export type ChangeKind = "added" | "removed" | "modified";
export type AckOutcome =
  | "pending"
  | "no_changes"
  | "cancelled"
  | "kept"
  | "deferred"
  | "applied_no_warnings"
  | "reverted_applied"
  | "override_applied"
  | "unverified_bypass_applied"
  | "aborted_plan_changed"
  | "failed";

export interface Rule {
  protocol: string | null;
  portRange: string | null;
  sourceAddresses: string[];
  sourceTags: string[];
  sourceDropletIds: string[];
  sourceLoadBalancerUids: string[];
  sourceKubernetesIds: string[];
}

export interface EmergencyRecord {
  id: string;
  environment: string;
  resourceAddress: string;
  attribute: string;
  changeKind: ChangeKind;
  baseline: Rule | null;
  observed: Rule | null;
  summary: string;
  firstDetectedAt: string; // when our scan FIRST DETECTED it, not when it changed
  lastDetectedAt: string;
  reporter: string | null; // self-reported
  reason: string | null; // self-reported; null = unexplained
  reportedAt: string | null;
  intent: Intent;
  intentNote: string | null;
  resolution: Resolution;
  resolutionReason: string | null;
  lastCheckStatus: CheckStatus;
  lastCheckAt: string | null;
  evidenceSource: string;
}

export interface HealthAuth {
  /** Server requires a Google sign-in for report/decision. */
  writesRequireSignIn: boolean;
  adminViaFirebase: boolean;
  adminViaSharedToken: boolean;
}

export interface Health {
  status: string;
  db: string;
  environment: string;
  time: string;
  /** Sign-in configuration; null when the server doesn't report it. */
  auth?: HealthAuth | null;
}

export interface RecordList {
  records: EmergencyRecord[];
  health: Health | null; // null = health endpoint unreachable
}

export interface ProposedChange {
  resourceAddress: string;
  actions: string[];
  summary: string;
}

export interface ApplyWarning {
  recordId: string;
  resourceAddress: string;
  message: string; // server-composed plain text
  reason: string | null;
  reporter: string | null;
  intent: Intent;
  firstDetectedAt: string;
}

export interface ApplyRun {
  id: string;
  environment: string;
  generatedAt: string;
  planFingerprint: string | null;
  proposedChanges: ProposedChange[];
  warnings: ApplyWarning[];
  checkStatus: CheckStatus;
  coverageNote: string;
  ackOutcome: AckOutcome;
  ackNote: string | null;
  completedAt: string | null;
}

export type AdminEventType =
  | "change_detected"
  | "explained"
  | "decision"
  | "review"
  | "run_started"
  | "run_finished"
  | "run_unfinished"
  | "resolved";
/** A terminal run outcome, or "unknown" (no completion recorded; NOT the same as failed). */
export type RunOutcome = AckOutcome | "unknown";

export interface AdminEvent {
  at: string;
  type: AdminEventType;
  environment: string;
  recordIds: string[];
  runId: string | null;
  resourceAddresses: string[];
  actor: string | null;
  /** "self-reported" | "local-os-user (not verified)" | "system": never a verified identity. */
  actorAssurance: string;
  outcome: RunOutcome | null;
  planFingerprint: string | null;
  detail: string | null;
}
export interface AdminLog {
  events: AdminEvent[];
  totalMatching: number;
  limitations: string[];
}
export interface TimelineGap {
  code: string;
  message: string;
  runId: string | null;
}
export interface Timeline {
  recordId: string;
  events: AdminEvent[];
  gaps: TimelineGap[];
  limitations: string[];
}
export interface AdminFilters {
  engineer?: string;
  resource?: string;
  outcome?: RunOutcome;
  since?: string; // ISO 8601 with timezone
  until?: string;
}

export interface Adapter {
  listRecords(): Promise<RecordList>;
  getRecord(id: string): Promise<EmergencyRecord>;
  report(
    id: string,
    body: { reporter: string | null; reason: string; intent?: Intent },
  ): Promise<EmergencyRecord>;
  decide(id: string, intent: Intent, note?: string): Promise<EmergencyRecord>;
  getApplyRun(id: string): Promise<ApplyRun>;
  /** The token is passed per call and held by the caller in memory only. */
  adminLog(token: string, filters: AdminFilters): Promise<AdminLog>;
  adminTimeline(token: string, recordId: string): Promise<Timeline>;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// ---- wire mapping ----
type Wire = Record<string, any>; // eslint-disable-line

function fromWireRule(w: Wire | null): Rule | null {
  if (!w) return null;
  return {
    protocol: w.protocol ?? null,
    portRange: w.port_range ?? null,
    sourceAddresses: w.source_addresses ?? [],
    sourceTags: w.source_tags ?? [],
    sourceDropletIds: w.source_droplet_ids ?? [],
    sourceLoadBalancerUids: w.source_load_balancer_uids ?? [],
    sourceKubernetesIds: w.source_kubernetes_ids ?? [],
  };
}

export function fromWireRecord(w: Wire): EmergencyRecord {
  return {
    id: w.id,
    environment: w.environment,
    resourceAddress: w.resource_address,
    attribute: w.attribute,
    changeKind: w.change_kind,
    baseline: fromWireRule(w.baseline_value),
    observed: fromWireRule(w.observed_value),
    summary: w.summary,
    firstDetectedAt: w.first_detected_at,
    lastDetectedAt: w.last_detected_at,
    reporter: w.reporter ?? null,
    reason: w.reason ?? null,
    reportedAt: w.reported_at ?? null,
    intent: w.intent ?? "unset",
    intentNote: w.intent_note ?? null,
    resolution: w.resolution,
    resolutionReason: w.resolution_reason ?? null,
    lastCheckStatus: w.last_check_status,
    lastCheckAt: w.last_check_at ?? null,
    evidenceSource: w.evidence_source,
  };
}

export function fromWireApplyRun(w: Wire): ApplyRun {
  return {
    id: w.id,
    environment: w.environment,
    generatedAt: w.generated_at,
    planFingerprint: w.plan_fingerprint ?? null,
    proposedChanges: (w.proposed_changes ?? []).map((c: Wire) => ({
      resourceAddress: c.resource_address,
      actions: c.actions ?? [],
      summary: c.summary,
    })),
    warnings: (w.warnings ?? []).map((x: Wire) => ({
      recordId: x.record_id,
      resourceAddress: x.resource_address,
      message: x.message,
      reason: x.reason ?? null,
      reporter: x.reporter ?? null,
      intent: x.intent ?? "unset",
      firstDetectedAt: x.first_detected_at,
    })),
    checkStatus: w.check_status,
    coverageNote: w.coverage_note ?? "",
    ackOutcome: w.ack_outcome,
    ackNote: w.ack_note ?? null,
    completedAt: w.completed_at ?? null,
  };
}

function fromWireAdminEvent(w: Wire): AdminEvent {
  return {
    at: w.at,
    type: w.type,
    environment: w.environment,
    recordIds: w.record_ids ?? [],
    runId: w.run_id ?? null,
    resourceAddresses: w.resource_addresses ?? [],
    actor: w.actor ?? null,
    actorAssurance: w.actor_assurance ?? "system",
    outcome: w.outcome ?? null,
    planFingerprint: w.plan_fingerprint ?? null,
    detail: w.detail ?? null,
  };
}

export function fromWireAdminLog(w: Wire): AdminLog {
  return {
    events: (w.events ?? []).map(fromWireAdminEvent),
    totalMatching: w.total_matching ?? 0,
    limitations: w.limitations ?? [],
  };
}

export function fromWireTimeline(w: Wire): Timeline {
  return {
    recordId: w.record_id,
    events: (w.events ?? []).map(fromWireAdminEvent),
    gaps: (w.gaps ?? []).map((g: Wire) => ({
      code: g.code,
      message: g.message,
      runId: g.run_id ?? null,
    })),
    limitations: w.limitations ?? [],
  };
}

async function raw(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Backend unreachable", 0);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    let code: string | undefined;
    try {
      const body = await res.json();
      if (typeof body?.error?.message === "string") msg = body.error.message;
      code = body?.error?.code;
    } catch {
      /* non-JSON body, e.g. proxy error */
    }
    if (res.status === 502 || res.status === 503 || res.status === 504)
      msg = "Backend unavailable";
    throw new ApiError(msg, res.status, code);
  }
  return (await res.json()) as T;
}

/**
 * Supplies a fresh Firebase ID token for writes (set by AuthProvider), or null
 * when nobody is signed in. Called per request, never cached here.
 */
let tokenProvider: (() => Promise<string | null>) | null = null;
export function setTokenProvider(fn: (() => Promise<string | null>) | null) {
  tokenProvider = fn;
}
async function signedInHeaders(): Promise<Record<string, string>> {
  const t = tokenProvider ? await tokenProvider() : null;
  // Bearer header only: an ID token is never put in a URL.
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function getHealth(): Promise<Health | null> {
  try {
    const res = await raw("/health");
    // 503 carries the same body shape with status "degraded"
    const w = await res.json();
    return {
      status: w.status,
      db: w.db,
      environment: w.environment,
      time: w.time,
      auth: w.auth
        ? {
            writesRequireSignIn: w.auth.writes_require_sign_in === true,
            adminViaFirebase: w.auth.admin_via_firebase === true,
            adminViaSharedToken: w.auth.admin_via_shared_token === true,
          }
        : null,
    };
  } catch {
    return null;
  }
}

const realAdapter: Adapter = {
  async listRecords() {
    const [w, health] = await Promise.all([
      http<Wire>("/records?resolution=open"),
      getHealth(),
    ]);
    return { records: (w.records ?? []).map(fromWireRecord), health };
  },
  async getRecord(id) {
    return fromWireRecord(await http(`/records/${encodeURIComponent(id)}`));
  },
  async report(id, b) {
    return fromWireRecord(
      await http(`/records/${encodeURIComponent(id)}/report`, {
        method: "POST",
        headers: await signedInHeaders(),
        body: JSON.stringify({
          reporter: b.reporter,
          reason: b.reason,
          ...(b.intent ? { intent: b.intent } : {}),
        }),
      }),
    );
  },
  async decide(id, intent, note) {
    return fromWireRecord(
      await http(`/records/${encodeURIComponent(id)}/decision`, {
        method: "POST",
        headers: await signedInHeaders(),
        body: JSON.stringify({ intent, ...(note ? { note } : {}) }),
      }),
    );
  },
  async getApplyRun(id) {
    return fromWireApplyRun(
      await http(`/apply-runs/${encodeURIComponent(id)}`),
    );
  },
  // Bearer header only: a token is never put in a URL.
  async adminLog(token, f) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) q.set(k, v);
    const qs = q.toString();
    return fromWireAdminLog(
      await http(`/admin/log${qs ? `?${qs}` : ""}`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  },
  async adminTimeline(token, id) {
    return fromWireTimeline(
      await http(`/admin/records/${encodeURIComponent(id)}/timeline`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  },
};

/** Fixtures only when explicitly requested: VITE_API_MODE=fixture or ?fixture… */
export const usingFixtures =
  import.meta.env.VITE_API_MODE === "fixture" ||
  (typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("fixture"));

let override: Adapter | null = null;
/** Test hook. */
export function setAdapter(a: Adapter | null) {
  override = a;
}
export const api: Adapter = new Proxy({} as Adapter, {
  get: (_t, k: keyof Adapter) =>
    ((override ?? (usingFixtures ? fixtureAdapter : realAdapter)) as Adapter)[
      k
    ],
});
