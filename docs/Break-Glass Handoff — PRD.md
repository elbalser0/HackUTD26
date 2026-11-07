---
title: Break-Glass Handoff — PRD
status: draft-v3
source_type: conversation-and-attached-prd
source_file: PRD-break-glass-handoff-6.md
---

# Product Requirements Document: Break-Glass Handoff (working title)

**Author:** Daniel  
**Date:** 2026-11-07 (source PRD date)  
**Status:** Draft v3 — updated product direction; implementation not verified  
**Context:** HackUTD26, NMC² challenge, 24-hour build  
**Changes from v2:** required apply-time review through the wrapper; persistent decision and execution history; admin visibility across engineers; agent-assisted classification and incident-pattern analysis added to the product direction. Core demo and analytics extension are separated below; extension priority remains proposed.

## 1. Summary

During an incident, an engineer may manually change infrastructure without immediately updating Terraform. A later apply can undo that fix. The incoming engineer can see the planned difference but may not know why the emergency change exists or whether it is safe to overwrite.

Break-Glass Handoff connects three moments: **capture the emergency context, require review before a conflicting apply, and preserve the decision for later investigation.** Engineers must use the wrapper as the team's approved deployment path. When a plan would undo a recorded emergency change, the wrapper pauses, displays the change and its recorded explanation, and requires an explicit decision and acknowledgement before proceeding. It does not prove safety or make the decision for the engineer.

A persistent shared log records observed changes, reported explanations, review decisions, and wrapper execution outcomes. An authorized admin dashboard lets team leads inspect the history across engineers and trace the sequence preceding a failure. A classifying agent can organize this evidence and highlight recurring patterns. Identifying actions associated with the most downtime additionally requires linked incident durations or health evidence; decision logs alone cannot establish causation.

**Problem/solution statement**

> When engineers deploy infrastructure after emergency changes, the engineer running the deployment struggles to verify that those changes can safely be overwritten because their purpose and prior decisions are scattered or undocumented. Our solution helps them review and acknowledge affected emergency changes before applying, while preserving a shared decision history, improving pre-deployment review coverage and reducing the time teams spend reconstructing deployment decisions after failures.

These benefits are hypotheses to validate, not measured results.

## 2. Contacts

- Daniel: product, frontend.
- Samuel: backend.
- Andrew: infrastructure.
- Roles are starting strengths, not fixed assignments.

## 3. Background and positioning

### Sponsor context

- **Challenge-text requirement, as recorded in v2:** help data center teams stay one step ahead; examples include missed warnings, unclear handoffs, and wrong information at the wrong time. No mandatory technology was recorded.
- **Informal guidance:** a booth representative expressed interest in infrastructure as code. This is not a stated Terraform requirement.
- **Unvalidated hypothesis:** NMC² teams experience emergency-change handoff pain and would adopt this workflow. Their Terraform/Ansible usage and judging rubric remain unknown.

### Existing alternatives and hypothesized gap

The source PRD cites public accounts of emergency fixes being overwritten by infrastructure reconciliation. A normal Terraform plan already exposes the intended change; this product does not claim novel diff detection.

Alternatives identified in v2 include drift tools, plan-level gates, deployment-platform hooks, incident tickets, Slack handoffs, and a manual rule to reconcile emergency fixes into code. Examples named there include Terraform Cloud, Spacelift, Scalr, env0, drifty, and Argo CD. This comparison is inherited research, not a fresh feature audit; competitors may support context, approvals, or audit histories. We do not claim those capabilities are absent elsewhere.

**Hypothesized value:** emergency context carried into the specific apply that could undo the fix, an explicit review decision on the approved deployment path, and a shared history usable during incident investigation. Adoption and differentiation still need operator validation.

## 4. Objectives and success measures

### Product outcomes — proposed measurements

- **Review coverage:** affected wrapped applies with a persisted explicit acknowledgement divided by all wrapped applies identified as reverting recorded emergency changes. Direct applies are outside this denominator unless independently observed.
- **Investigation time:** time an evaluator takes to find the relevant change, explanation, reviewer decision, and execution outcome in a staged incident, compared with the existing workflow.
- **History completeness:** proportion of wrapped runs with linked plan, decision where required, and terminal outcome. Interrupted or missing outcomes are shown as unknown.
- **Longer-term outcome:** fewer repeat incidents caused by unintentional emergency-fix reversions. Requires real incident evidence; not demonstrated by an acknowledgement screen.
- **Analytics extension:** human-reviewed classification accuracy and incident-link coverage before interpreting downtime rankings.

### Hackathon targets retained from v2

1. A console change appears as a persistent record in the UI by hour 4.
2. Full live demo takes no more than 3 minutes; recorded fallback ready 3 hours before judging.
3. Demonstrate a paused apply, explicit acknowledgement, cancellation, and the missing-reason case.
4. Verify Terraform refresh-only detection against the staged change.
5. Seek at least 2 sponsor conversations by hour 10 to test pain and workflow fit.

These are planning targets from the original schedule, not completed milestones or a claim about time remaining.

## 5. Users and value propositions

### Primary: engineer running Terraform apply

Needs the reason behind an emergency change before undoing it. The wrapper brings the context into the deployment flow and requires a deliberate choice rather than an easily missed dashboard warning.

### Secondary: incoming shift engineer or shift lead

Needs a shared list of unresolved changes, explanations, and prior decisions without depending on the previous engineer's memory.

### Admin: authorized operations lead or incident investigator

Needs to browse records across engineers, reconstruct decision and execution timelines, and identify recurring failure patterns. The dashboard supports investigation and process improvement, not unsupported blame or individual performance rankings.

**Build audience:** hackathon judges and NMC² representatives.

## 6. End-to-end workflow

1. Terraform provisions a dedicated demo server and DigitalOcean firewall before judging.
2. During a staged incident, an engineer manually changes a tracked firewall setting in the DigitalOcean control panel. This is the source-PRD demo proposal, not evidence of a completed spike.
3. A Terraform refresh-only plan detects the change. The system stores resource identity, attribute, previous and observed values, and detected-at time.
4. The web app presents a pre-filled, one-line explanation prompt, answerable in about ten seconds. The engineer supplies what changed and why; the explanation persists after reload. CLI/Slack capture remains an optional future interface, not a separate data store.
5. Later, another engineer invokes the wrapper. It creates and examines a normal execution plan and matches planned reversions to emergency records.
6. For a matched reversion, the terminal displays the affected setting, recorded explanation or **“No reason recorded,”** record age, and prior decisions. Terraform must not execute while the review is pending.
7. The engineer either explicitly acknowledges proceeding with the displayed reversion or cancels. Keep/defer choices cancel this run; keep may suggest a manual Terraform edit. The system records the decision and a short rationale separately from the original incident explanation.
8. Before proceeding, the decision must be durably saved. The wrapper executes only the reviewed plan. A changed/replaced plan requires fresh review; a rejected stale plan must not silently trigger a new unreviewed apply.
9. The system records run start and observed outcome: succeeded, failed, cancelled, or unknown/interrupted. Terraform success does not establish service health.
10. A subsequent observation verifies reconciliation before closing the emergency record. Acknowledgement or choosing keep does not itself resolve drift.
11. The admin dashboard displays the persistent history across engineers, with drill-down to the evidence behind each record.
12. In the analytics extension, linked incident/health evidence supports agent classifications and suspected contributing patterns. Humans review the findings; the agent cannot approve applies or change infrastructure.

## 7. Functional requirements

### Core demo: review, persistent history, and admin visibility

| ID | Requirement |
| --- | --- |
| R1 | Detect the staged manual change using Terraform refresh-only plan JSON for provider-tracked attributes. |
| R2 | Persist observed values, resource identity, detection time, explanation, and reported author. |
| R3 | Capture the explanation in the web app and show outstanding records to the next shift. |
| R4 | Match a planned reversion to the applicable emergency record and show its context in the wrapper terminal. |
| R5 | Pause the affected apply until explicit acknowledgement; allow cancellation, including when no reason was recorded. |
| R6 | Persist review decisions and rationales, including cancellation/defer decisions, without overwriting earlier history. |
| R7 | Link the acknowledgement to the exact reviewed plan and persist it before Terraform executes. If review or logging fails, do not execute that affected apply; explain the failure. |
| R8 | Persist wrapper execution outcomes and show unknown when completion evidence is missing. |
| R9 | Provide an authorized admin dashboard with team-wide log browsing, engineer/resource/time/outcome filters, and a linked change → explanation → decision → run timeline. |
| R10 | Preserve history after record closure and across application restarts. Corrections create new events instead of silently replacing past decisions. |
| R11 | Close a change record only after a successful re-check verifies the relevant drift is gone. |
| R12 | Suggest a manual configuration edit for a single literal value; never automatically patch or reconcile infrastructure. |

### Agent-assisted analysis: agreed direction, proposed post-core phase

- Classify logged actions into categories such as firewall/network change, configuration reconciliation, unexplained change, acknowledgement, cancellation, and failed apply. Proposed taxonomy must be validated against real records.
- Keep source records intact; store classifications as derived outputs with evidence record IDs, model/version, classification time, and uncertainty or an insufficient-evidence result.
- Link incidents to affected resources and runs, with start/end times, link provenance, and human review status. A manually recorded incident is acceptable initially; it must be labeled as such.
- Show action-category counts, failed-run counts, and recurring sequences. Label Terraform execution failures separately from service incidents.
- Show associated downtime by category only when incident timing and linkage exist. Explain the aggregation and avoid double-counting overlapping incidents in overall totals.
- Present suspected contributors, not proven root causes. No evidence means **“Downtime attribution unavailable,”** not zero downtime.
- Let an authorized reviewer correct classifications and incident links while retaining the previous classification and review trail.

The dashboard's persistent log view is core. Agent classification and downtime analysis are part of the product direction; their hackathon release priority remains an open team decision, not an implemented capability.

## 8. Data, architecture, and trust boundaries

### Architecture

A shared backend and persistent store serve the explanation web app, wrapper, and admin dashboard. Terraform refresh-only JSON supplies observations; normal plan JSON supplies proposed actions. The wrapper links review decisions to execution. An isolated analysis component reads approved, redacted records and writes derived findings. Ansible check mode with diff remains a stretch detector for OS-level changes.

### Minimum records

- **Emergency change:** ID, workspace/environment, resource address and attribute, prior/observed values, detected-at, self-reported author/reason, optional reported change time, status, and verification evidence.
- **Review event:** ID, emergency-record IDs, run ID, reviewed plan reference/fingerprint, reviewer identity and its assurance level, decision, acknowledgement time, rationale.
- **Run event:** ID, initiator, environment, reviewed plan reference, timestamps, execution status and redacted result summary.
- **Incident evidence (analytics):** ID, affected service/resource, start/end or ongoing status, source, linked runs/changes, review status.
- **Classification (analytics):** ID, source IDs, category, suspected-contributor explanation, model/version, uncertainty, and reviewer correction history.

**Identity:** a person reporting a cloud-console change is not automatically its verified author. An authenticated wrapper reviewer is the reviewer, not proof they made the original change. Demo aliases must be labeled; production-grade identity integration remains open.

**Authorization and privacy:** team-wide log access requires server-side admin authorization, not just a hidden UI route. “All logs” means records captured within the team's connected scope, not all engineer activity. Do not persist credentials, full sensitive state, or unredacted plan secrets. Retention duration and production audit-tamper protections remain open; append-only application behavior is not a compliance-grade immutable audit guarantee.

### Enforcement and honesty

- Engineers must use the wrapper as the approved workflow. Running Terraform directly can bypass the prototype; universal interception is not promised.
- Strong enforcement needs restricted deployment credentials and a required CI/deployment path. That integration is stretch, not an achieved guarantee.
- The review pause is mandatory on the supported path. It is not a permanent policy veto and does not automatically decide whether a change is safe.
- No automatic apply without the engineer's authorization, no automatic revert, and no agent-driven infrastructure changes.
- Detected-at is not necessarily changed-at. Unanswered explanations remain visible as missing.
- Terraform sees only provider-tracked attributes. OS changes may remain invisible.
- A successful apply is not verified uptime; correlation is not causation.

## 9. Release and acceptance

### Must-have demo

Dedicated pre-provisioned server; Terraform detector; persisted web explanation; terminal review pause; acknowledgement/cancel; persistent decision and run history; basic authorized admin log view; fake names; recorded fallback.

### Acceptance checklist — not executed verification

- [ ] A staged console change is detected and appears in the web app.
- [ ] Its explanation survives page reload and application restart.
- [ ] A matching reversion pauses before Terraform execution and displays the explanation.
- [ ] Without acknowledgement, no affected apply starts; cancellation makes no infrastructure change.
- [ ] Missing explanations still trigger review with “No reason recorded.”
- [ ] Acknowledged execution uses the reviewed plan; changed plans require review again.
- [ ] Failure to persist the required decision prevents execution and produces a clear error.
- [ ] Decisions and observed execution outcomes remain visible after restart and record closure.
- [ ] The admin can filter and trace events from different demo engineers; unauthorized access is rejected server-side.
- [ ] Reconciliation is verified before closure; an interrupted run is not reported as successful.

### Analytics extension acceptance

- [ ] A classifier produces categories linked to actual stored source records.
- [ ] Findings expose evidence and uncertainty; missing incident data produces unavailable attribution.
- [ ] Linked incident timing supports a clearly labeled associated-downtime view without claiming proven causality.
- [ ] Human corrections remain traceable; the agent cannot authorize or execute infrastructure operations.

### Other stretch items

CI-enforced path, Ansible detector, health-check integration, and drafted handoff notes.

### Non-goals

Universal monitoring of engineer activity; automatic remediation; autonomous root-cause declarations; employee blame scores; production-grade compliance auditing; paging; multi-tenancy; arbitrary state conversion; access to Andrew's network or production systems; novelty claims.

**Safety:** dedicated new server, explicit team approval before infrastructure operations, restricted SSH, DigitalOcean token only in an environment variable and never in chat/repo/logs, and server cleanup afterward. This document authorizes no infrastructure action.

## 10. Assumptions, risks, and open decisions

- Verify the staged firewall change appears in refresh-only JSON and can be matched reliably to an execution-plan reversion.
- Confirm detection trigger: manual scan, polling, or another mechanism.
- Confirm the source-PRD DigitalOcean scenario with the team.
- Define behavior for partial/failed observations; do not present unknown state as healthy.
- Choose identity mechanism, admin authorization, retention period, and minimal logging implementation.
- Confirm whether classification fits the hackathon release or follows the core demo. Select a bounded incident-evidence source before promising downtime analysis.
- Validate operator willingness to adopt the wrapper and whether existing deployment tools already solve the context/history need.
- Risks: live-demo failure, wrapper bypass, plan/review mismatch, logging outages, sensitive-data leakage, incorrect attribution, classification errors, expanding analytics before the core slice works, and unvalidated customer demand.

## 11. Decision log and provenance

- **Inherited from v2:** Terraform primary detector; Ansible stretch; human infrastructure decisions; self-reported explanations; dedicated safe demo environment.
- **Earlier requirements note:** web explanation capture with persistence; terminal warning; acknowledgement with cancel/continue; missing-reason warning. See [[Break-Glass Handoff — Requirements]].
- **Daniel's additions in this discussion:** engineers use the wrapper; required pre-apply verification/acknowledgement; persistent log of decisions; admin access to logs across engineers; classifying agent to identify recurring actions associated with downtime.
- **Clarifications retained:** acknowledgement does not prove safety; direct apply can bypass the prototype; downtime diagnosis requires outcome evidence and cannot be inferred from decision logs alone.
- **Proposed sequencing, not a new confirmed team decision:** build core review/history/admin view first, then classification and incident-linked analytics.

This draft updates the attached `PRD-break-glass-handoff-6.md` and supersedes conflicting scope language in the earlier simple requirements note. It records requirements and proposals, not implementation or executed acceptance results.

## 12. Sources inherited from v2

These references are preserved for follow-up; external capabilities and historical claims were not re-verified during this editing pass.

- Spacelift, “Ansible Configuration Drift Management”: https://spacelift.io/blog/ansible-configuration-drift-management
- Razorpay Engineering, “The Dark Side of Terraform Drifts”: https://engineering.razorpay.com/the-dark-side-of-terraform-drifts-chaos-and-the-headaches-they-bring-186ce3a068b6
- drifty on PyPI: https://pypi.org/project/drifty/
- DigitalOcean Terraform provider resources: https://docs.digitalocean.com/reference/terraform/reference/resources/
- DigitalOcean community discussion of audit API availability (not authoritative proof of current attribution limits): https://www.digitalocean.com/community/questions/digitalocean-api-audit-log
- DigitalOcean team security history: https://docs.digitalocean.com/platform/teams/how-to/view-security-history/
- Terraform issue requesting pre-apply hooks: https://github.com/hashicorp/terraform/issues/32930
- Scalr hooks: https://docs.scalr.io/docs/hooks-1
