# HackUTD26

Private HackUTD 2026 team workspace, preparing for the NMC² challenge. **Official challenge pending.** Infrastructure as code is an unconfirmed booth hint, not an implemented product requirement.

## Run locally

Node 22.12+ (Node 22 recommended) and npm required.

```sh
git clone https://github.com/elbalser0/HackUTD26.git
cd HackUTD26
npm ci
npm run dev
```

Open the localhost URL printed by Vite. You need repository access to clone. No secrets, backend, home-server access, or cloud account required.

## Included

- React + TypeScript + Vite; lightweight CSS, no component-library lock-in.
- Responsive dark workspace inspired by NMC²’s black/white/blue palette.
- Workspace, challenge notes, and team navigation.
- Browser-local note persistence with storage-error handling. Notes are **not shared or synced**.
- Unit/component tests and GitHub Actions for lint, test, and production build.

```sh
npm run lint
npm test
npm run build
npm run preview
npm run format
```

## Where to work

- `src/App.tsx`: workspace views and initial reusable Panel component.
- `src/index.css`: typography and design tokens.
- `src/App.css`: responsive layout and component styles.
- `src/App.test.tsx`: navigation, honest empty state, persistence, storage-failure coverage.
- [Living project document](docs/PROJECT.md): context, ownership, decisions, open questions, next decision gate.

The frontend makes no API calls and provisions nothing. Do not put secrets in `VITE_*` variables; they are public bundle values. Agree on one backend contract after the brief arrives. Roboto loads from Google Fonts with a local Arial fallback; no dependency on that request succeeding.

## Team starting points

Daniel: product/frontend · Samuel: backend · Andrew: infrastructure exploration. Roles are flexible. Home-server use remains unvalidated.

## Design / affiliation

Visual reference: https://nmc2.com/ — black and white, blue `#2b9cfc`, light oversized typography, geometric blue imagery. CSS artwork and H² project mark are original. This is an independent hackathon project, not affiliated with or endorsed by NMC².

## Verification

Initial local checks: lint, four component tests, and TypeScript/production build passed. GitHub Actions repeats these checks on pushes and pull requests. No backend or provisioning tests exist yet. Nothing is publicly deployed.
