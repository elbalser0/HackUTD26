## Product Requirements Document: Break-Glass Handoff (working title)

**Author**: Daniel
**Date**: 2026-11-07
**Status**: Draft v2 (HackUTD26, NMC² challenge, 24-hour build)
**Change from v1**: the hero is now an apply-time warning ("git blame for emergency changes"); Terraform is the primary detector; Ansible is a stretch detector; honesty caveats added.

---

### 1. Summary

When an engineer fixes infrastructure by hand during an incident, the next `terraform apply` can silently undo that fix and bring the outage back. Break-Glass Handoff detects the manual change, asks the engineer a one-line question (what did you change and why?), stores the answer as an emergency-change record, and warns before a later apply would revert it: *"This will close port 8443. Paul reported opening it yesterday: 'payment webhook blocked.'"* A human always decides; nothing is auto-applied, auto-reverted or auto-blocked.

### 2. Contacts

- Daniel: product, frontend
- Samuel: backend
- Andrew: infrastructure
- Roles are starting strengths, not fixed assignments.

### 3. Background

**Sponsor input, kept separate**
- *Requirement (challenge text only):* build something that helps data center teams stay one step ahead. The text names missed warnings, unclear handoffs, and wrong information at the wrong time. No mandatory technology.
- *Informal guidance:* a booth representative said it would be cool to see infrastructure as code. Not a stated requirement. Whether they meant Terraform specifically is unknown.
- *Hypothesis:* the sponsor's teams hit manual-fix handoff pain. Unvalidated.

**The problem is documented.** Public write-ups describe manual emergency fixes being wiped by the next apply or run (see Sources).

**Existing alternatives (searched, not exhaustive)**
- Drift detection: Terraform Cloud, Spacelift, Scalr, env0, drifty (AWS attribution via CloudTrail), Argo CD self-heal.
- Plan-time gates that check plan JSON and warn or block on risky changes. They do not know about human emergency context.
- Pre-apply hooks in platforms such as Scalr; Terraform itself has no native pre-apply hook (an open feature request exists).
- A plain plan already shows the revert. We do not claim novelty in detection.

**Where we think the gap is (hypothesis, unverified):** the human context (what and why) shown at the exact moment of an apply, with a decision attached.

**Attribution reality on DigitalOcean:** a community answer says no API endpoint logs who changed firewall rules or tags (the poster only believes this). The control panel has a team security history. So who and why must be self-reported.

### 4. Objective

**Goal:** a credible, live-demonstrable workflow showing how apply-time context prevents a self-inflicted repeat outage.

**Success measures (proposed targets)**
1. Vertical slice (a console change appears as a record in the UI) by hour 4.
2. The full demo runs live in 3 minutes or less, with a recorded fallback ready 3 hours before judging.
3. The apply-time warning fires in the demo, including the "no reason recorded" case.
4. The staged change is detected by Terraform's refresh-only plan.
5. At least 2 sponsor conversations by hour 10 to test the handoff pain.

### 5. Market Segment(s)

- **Primary:** on-call and shift engineers running small to mid-size fleets managed with Terraform.
- **Secondary:** shift leads who inherit what the previous shift did.
- **Audience for this build:** hackathon judges and NMC² representatives.

### 6. Value Proposition(s)

- **Who:** the engineer about to run an apply.
- **Why:** they cannot see that a live setting was changed by hand, or why.
- **What before:** the apply quietly reverts the fix and the outage returns; the on-call debugs a repeat incident.
- **How:** the layer records the change with a self-reported reason and warns before the apply, with keep, revert or defer as options.
- **What after:** the engineer makes a deliberate choice with the context in front of them.
- **Alternatives:** a plain plan, drift tools such as drifty, plan-level gates, scheduled checks plus Slack, the manual PR-within-24-hours rule.

### 7. Solution

**Flow**
1. Terraform provisions the demo server and its DigitalOcean firewall (pre-provisioned before judging).
2. During the "incident", someone changes the firewall in the console (for example, opens a port).
3. The detector runs a Terraform refresh-only plan and reads the JSON. The core opens a record: what changed, old and new values, detected-at time.
4. The core sends a one-line prompt (CLI or Slack) with the changed values pre-filled: what did you change and why? The person answers and optionally picks keep, revert or not sure.
5. Later, someone runs apply through the wrapper. The wrapper reads the plan JSON, matches it against open records, and shows the warning. The user must acknowledge before continuing.
6. A decision card shows the revert preview, the record's age and reason, and a labeled heuristic suggestion. On keep, the product suggests an edit to the Terraform firewall rule. A re-check closes the record once drift is gone.

**Honesty rules (built into the UI and the pitch)**
- The timestamp is *detected-at*, not when the change happened, unless the person reports a time. Label it "detected 03:30".
- Who and why are self-reported: show "reported by Paul", never "verified".
- If nobody answers the prompt, the warning still fires: "unexplained manual change, no reason recorded."
- The prompt must be one line and pre-filled, answerable in about ten seconds.
- Terraform only sees attributes its provider tracks. Edits inside the operating system are invisible to it.
- The wrapper is a gate on the approved path, not enforcement; it can be bypassed by running Terraform directly. A CI step is the enforceable version (stretch).
- Warn and require acknowledgement. Never auto-block, auto-apply or auto-revert.

**Architecture:** a tool-agnostic core (record, prompt, decision, warning) plus a detector adapter. Terraform refresh-only is primary. Ansible check mode with diff is a stretch adapter for OS-level changes.

**IaC role:** Terraform creates the fleet and its firewall, and its plan JSON is the central input to both detection and the warning.

**In scope for the first version**
- Record model: what changed, old and new values, detected-at, reported-by, reason, state.
- Terraform refresh-only detector for tracked cloud attributes.
- One-line prompt, wrapped apply with warning, next-shift list of open records.
- Suggested edit for a single literal value (no automatic patching).

**Assumptions and open questions**
- Refresh-only reports a console firewall change (to verify in a spike).
- Plan JSON resource addresses can be matched reliably to records.
- Whether NMC² teams use Terraform or Ansible day to day is unknown.
- The judging rubric is unknown.

### 8. Release

**Must have for the demo:** items above, a dedicated pre-provisioned server, fake names in the demo, and a recorded fallback.
**Stretch:** Ansible detector, CI-enforced gate, health-check evidence on the decision card, drafted handoff note.
**Non-goals**
- No automatic apply, revert or block.
- No AI requirement (optional wording help only).
- No access to Andrew's network or production systems.
- No paging, multi-tenancy, or arbitrary state conversion.
- No novelty claims.

**Safety rules:** use a dedicated new server; keep the DigitalOcean token in an environment variable, never in chat or the repo; restrict SSH access; destroy the server afterward; no infrastructure operations without explicit team approval.

### Risks (summary of pre-mortem)
Live-demo failure, detection limited to staged changes, the "just drift detection" pitch, no early vertical slice, credential leakage, and an unanswered prompt.

### Sources
- Spacelift, "Ansible Configuration Drift Management": https://spacelift.io/blog/ansible-configuration-drift-management
- Razorpay Engineering, "The Dark Side of Terraform Drifts": https://engineering.razorpay.com/the-dark-side-of-terraform-drifts-chaos-and-the-headaches-they-bring-186ce3a068b6
- drifty on PyPI: https://pypi.org/project/drifty/
- DigitalOcean Terraform provider resources: https://docs.digitalocean.com/reference/terraform/reference/resources/
- DigitalOcean community, audit API question: https://www.digitalocean.com/community/questions/digitalocean-api-audit-log
- DigitalOcean, team security history: https://docs.digitalocean.com/platform/teams/how-to/view-security-history/
- Terraform issue requesting pre-apply hooks: https://github.com/hashicorp/terraform/issues/32930
- Scalr hooks: https://docs.scalr.io/docs/hooks-1
