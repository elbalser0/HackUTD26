# Argus hosted deployment — specification and runbook

## Authorized scope

Host the current HackUTD26 application at https://argus.artificial.cloud using Dokploy. Prepare infrastructure now; Daniel supplies configuration in Dokploy afterward. Never read or copy a local `.env`, provision infrastructure through Terraform, change shared database contents, seed data, or run migrations as part of this deployment.

## Topology and boundaries

- `argus-web`: repository-root Docker context, `deploy/web.Dockerfile`, target `production`, nginx on port 80, static SPA at `/`.
- `argus-api`: repository-root Docker context, `deploy/api.Dockerfile`, target `production`, uvicorn on port 8000, same host at `/api` WITHOUT stripping the prefix.
- Existing Tiger Cloud PostgreSQL remains the shared API/CLI store. No new database, SQLite fallback, migration, or backup policy changes. Existing schema and backup/restore readiness must be checked before accepting new real data.
- Firebase verifies identity; admin emails are server-side. The hosted API receives no DigitalOcean credentials or Terraform state/binary.
- API startup fails closed unless `BG_FIREBASE_PROJECT_ID` and `BG_DATABASE_URL` are nonempty. No API deployment until Daniel supplies settings.

## Acceptance

1. Existing frontend/backend tests and production build pass.
2. Images use supported Node/Python versions; secret-bearing files are excluded from build contexts.
3. Startup guard refuses missing production configuration (tested offline).
4. Dokploy repository, main branch, Docker targets, domain ports, and TLS settings read back correctly.
5. Frontend serves tested assets over trusted HTTPS. Real Firebase sign-in and shared database API checks remain pending user configuration.

## Frontend settings

In `argus-web` → Environment → **Build Arguments**, paste these with real PUBLIC Firebase identifiers from local config:

```dotenv
VITE_FIREBASE_API_KEY=REPLACE_FROM_LOCAL
VITE_FIREBASE_AUTH_DOMAIN=REPLACE_FROM_LOCAL
VITE_FIREBASE_PROJECT_ID=REPLACE_FROM_LOCAL
VITE_FIREBASE_APP_ID=REPLACE_FROM_LOCAL
```

These must be build arguments because Vite compiles them into JavaScript. Save and redeploy the frontend after changes. No API base URL setting is needed: the current frontend already requests `/api` on its own origin. Never set backend secrets here.

## Backend settings

In `argus-api` → Environment → **Environment Variables**, retain the prefilled safe defaults and add:

```dotenv
BG_DATABASE_URL=REPLACE_WITH_EXISTING_TIGER_CLOUD_RUNTIME_URL
BG_FIREBASE_PROJECT_ID=REPLACE_FROM_LOCAL
BG_ADMIN_EMAILS=REPLACE_WITH_COMMA_SEPARATED_ADMIN_EMAILS
```

Optional: `BG_ADMIN_TOKEN` only if the team still wants the shared-token fallback. Prefer Firebase-admin sign-in. The PostgreSQL role should not have DDL privileges. Do not copy `DIGITALOCEAN_TOKEN`, local file paths, or Terraform settings.

Prefilled safe defaults:

```dotenv
BG_NO_DOTENV=1
BG_ALLOWED_HOSTS=argus.artificial.cloud,localhost,127.0.0.1
BG_CORS_ORIGINS=https://argus.artificial.cloud
```

`BG_ENVIRONMENT` deliberately keeps the application's existing `demo` default; set it to match the local CLI if that uses another environment. Do not invent a new environment and assume existing records will appear.

Save and deploy the API after supplying settings. The startup guard prevents accidentally launching an unauthenticated public API or an ephemeral SQLite store. It does not validate schema or backups and never runs migrations.

## Firebase and final checks

Add `argus.artificial.cloud` to Firebase Authentication → Settings → Authorized domains. Keep the existing Firebase auth domain value. After configuring both services, verify `/api/health` reports PostgreSQL and sign-in required, unauthenticated record/admin requests are rejected, Google sign-in/out works, existing CLI records appear, admin authorization is correct, and data survives API restart. Do not claim those checks passed before configuration.

## Rollback

Stop only these two new applications or remove their two exact host/path routes. Do not change other domains or Tiger Cloud contents. Both services track `main`; later pushes may auto-deploy.
