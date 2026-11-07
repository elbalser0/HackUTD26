"""Shared domain types. This module is the contract between detector, matcher,
service, API and CLI. Keep it in sync with docs/API.md.

Conventions:
- Timestamps are timezone-aware datetimes, serialized as ISO 8601 with offset.
- Unknown values are None (JSON null), never invented defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .textsafe import has_control


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Intent(StrEnum):
    UNSET = "unset"
    KEEP = "keep"
    REVERT = "revert"
    UNSURE = "unsure"
    DEFER = "defer"


class Resolution(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ResolutionReason(StrEnum):
    VERIFIED_ALIGNED = "verified_aligned"
    SUPERSEDED = "superseded"


class CheckStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ChangeKind(StrEnum):
    ADDED = "added"        # rule exists live, absent from Terraform state
    REMOVED = "removed"    # rule in Terraform state, absent live
    MODIFIED = "modified"  # removed+added pair sharing protocol and sources (e.g. port 8080 -> 8443)


class AckOutcome(StrEnum):
    PENDING = "pending"
    NO_CHANGES = "no_changes"
    CANCELLED = "cancelled"
    KEPT = "kept"
    DEFERRED = "deferred"
    APPLIED_NO_WARNINGS = "applied_no_warnings"
    REVERTED_APPLIED = "reverted_applied"
    OVERRIDE_APPLIED = "override_applied"
    UNVERIFIED_BYPASS_APPLIED = "unverified_bypass_applied"
    ABORTED_PLAN_CHANGED = "aborted_plan_changed"
    FAILED = "failed"


# --------------------------------------------------------------------------
# Pure-layer value types (detector / rules / matcher). Plain dataclasses.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FirewallRule:
    """Normalized digitalocean_firewall inbound rule.

    port_range is a string as the provider models it ("8080", "8000-9000",
    "all") or None if unknown. Source collections are sorted tuples so that
    provider ordering never affects identity.
    """

    protocol: str | None
    port_range: str | None
    source_addresses: tuple[str, ...] = ()
    source_tags: tuple[str, ...] = ()
    source_droplet_ids: tuple[str, ...] = ()
    source_load_balancer_uids: tuple[str, ...] = ()
    source_kubernetes_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "port_range": self.port_range,
            "source_addresses": list(self.source_addresses),
            "source_tags": list(self.source_tags),
            "source_droplet_ids": list(self.source_droplet_ids),
            "source_load_balancer_uids": list(self.source_load_balancer_uids),
            "source_kubernetes_ids": list(self.source_kubernetes_ids),
        }

    def sources_key(self) -> tuple:
        return (
            self.source_addresses,
            self.source_tags,
            self.source_droplet_ids,
            self.source_load_balancer_uids,
            self.source_kubernetes_ids,
        )


@dataclass(frozen=True)
class Observation:
    """One supported discrepancy between Terraform state (baseline) and live
    infrastructure (observed), produced by the detector from a refresh-only plan.

    baseline is None for ADDED; observed is None for REMOVED.
    check_status is UNSUPPORTED when the evidence contains unknown/sensitive
    values that prevent a reliable comparison.
    """

    resource_address: str
    resource_type: str
    attribute: str  # "inbound_rule" is the only supported attribute
    kind: ChangeKind
    baseline: FirewallRule | None
    observed: FirewallRule | None
    check_status: CheckStatus = CheckStatus.CURRENT
    note: str | None = None


@dataclass(frozen=True)
class ProposedChange:
    """A resource_changes[] entry from a normal plan, summarized."""

    resource_address: str
    resource_type: str
    actions: tuple[str, ...]  # e.g. ("update",), ("delete","create")
    summary: str


@dataclass(frozen=True)
class MatchCandidate:
    """An open record, reduced to what the matcher needs."""

    record_id: str
    resource_address: str
    kind: ChangeKind
    baseline: FirewallRule | None
    observed: FirewallRule | None


@dataclass
class MatchResult:
    reversed_ids: list[str] = field(default_factory=list)  # plan provably reverses these records
    unknown_ids: list[str] = field(default_factory=list)   # plan touches the resource but reversal cannot be determined
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)        # non-empty means verification failed


@dataclass
class DetectionResult:
    observations: list[Observation] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)  # human-readable notes for drift we cannot interpret
    errors: list[str] = field(default_factory=list)       # parse problems; non-empty means verification failed


# --------------------------------------------------------------------------
# API schemas (pydantic). These are exactly what docs/API.md documents.
# --------------------------------------------------------------------------

class RuleOut(BaseModel):
    protocol: str | None
    port_range: str | None
    source_addresses: list[str]
    source_tags: list[str]
    source_droplet_ids: list[str]
    source_load_balancer_uids: list[str]
    source_kubernetes_ids: list[str]


class RecordOut(BaseModel):
    id: str
    environment: str
    resource_address: str
    resource_type: str
    attribute: str
    change_kind: ChangeKind
    baseline_value: RuleOut | None
    observed_value: RuleOut | None
    summary: str
    first_detected_at: datetime
    last_detected_at: datetime
    reporter: str | None
    reason: str | None
    reported_at: datetime | None
    intent: Intent
    intent_note: str | None
    intent_updated_at: datetime | None
    resolution: Resolution
    resolution_reason: ResolutionReason | None
    resolved_at: datetime | None
    superseded_by: str | None
    last_check_status: CheckStatus
    last_check_at: datetime | None
    evidence_source: str  # "terraform-refresh-only" | "authored-fixture" | "real-fixture"


class RecordList(BaseModel):
    records: list[RecordOut]


def _no_control_chars(v: str | None) -> str | None:
    if v is not None and has_control(v):
        raise ValueError("control or formatting characters are not allowed")
    return v


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporter: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    intent: Intent | None = None

    _check_text = field_validator("reporter", "reason")(_no_control_chars)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    note: str | None = Field(default=None, max_length=500)

    _check_text = field_validator("note")(_no_control_chars)


class ProposedChangeOut(BaseModel):
    resource_address: str
    resource_type: str
    actions: list[str]
    summary: str


class WarningOut(BaseModel):
    record_id: str
    resource_address: str
    message: str
    reason: str | None
    reporter: str | None
    intent: Intent
    first_detected_at: datetime


class ApplyRunOut(BaseModel):
    id: str
    environment: str
    generated_at: datetime
    plan_fingerprint: str | None
    proposed_changes: list[ProposedChangeOut]
    warnings: list[WarningOut]
    check_status: CheckStatus
    coverage_note: str
    ack_outcome: AckOutcome
    ack_note: str | None
    completed_at: datetime | None


class ApplyRunList(BaseModel):
    apply_runs: list[ApplyRunOut]


class HealthOut(BaseModel):
    status: str
    version: str
    db: str
    environment: str
    terraform_dir_configured: bool
    time: datetime
