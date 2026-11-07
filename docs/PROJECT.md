# HackUTD26 — Living project document

## Goal

Build for the NMC² challenge at HackUTD 2026. Official challenge not yet announced. Daniel also wants to explore product work and employment at NMC².

## Confirmed context

- Daniel: product and frontend starting focus.
- Samuel: backend starting focus.
- Andrew: home business-grade servers with 256 GB RAM and relevant hands-on experience.
- Everyone can flex. Hardware access and suitability are not validated.
- An NMC² booth representative mentioned “infrastructure as code.” This is an unconfirmed direction, not the official brief.

## Decisions

- Private GitHub repository: `elbalser0/HackUTD26` (preserve exact name).
- React + TypeScript + Vite in the repository root; npm lockfile committed.
- No backend framework, cloud provider, Terraform schema, or deployment chosen before the challenge.
- Frontend shell has workspace, browser-local challenge notes, and team context. No simulated cluster metrics or API calls.
- Palette from https://nmc2.com/: black/white, blue `#2b9cfc`; observed Roboto typography, thin oversized headlines, blue geometric imagery. Our geometric artwork is original CSS, not copied brand assets. Independent project, not an official NMC² product.

## Architecture and integration seam

`src/App.tsx` owns navigation and notes; `Panel` is the initial reusable surface. `src/index.css` defines shared tokens; `src/App.css` defines responsive layouts. No routing dependency needed for three local views. Notes use `hackutd26.brief` in localStorage and are not team-synced. No secrets or sensitive data should be placed there.

Once the brief arrives, choose one vertical slice and agree with Samuel on endpoint paths, typed request/response shapes, loading/empty/error states, and who owns each side. Do not assume browser access to Andrew’s home network. Keep privileged infrastructure operations server-side; never embed provider keys in Vite variables.

## Next decision gate

1. Paste exact official brief and judging criteria.
2. Identify target user and one painful workflow.
3. Select one measurable end-to-end demo.
4. Validate feasibility and permitted infrastructure access with Andrew.
5. Agree on backend contract and split work; integrate early.

## Progress

- Brand reference inspected directly in browser.
- Frontend scaffold implemented; verification results recorded in README and final handoff.
- Official challenge and real backend integration remain pending.

## Provenance

Team/role/hardware context and booth hint: Daniel’s kickoff message. Visual reference: https://nmc2.com/ inspected during kickoff. Do not treat marketing copy as challenge requirements.
