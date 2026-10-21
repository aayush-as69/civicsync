# Deploying CivicSync on Vercel (frontend + Flask API, one project)

Import settings: Root Directory `./`, Framework Preset `Other` (vercel.json sets build/output).

Environment variables (Project Settings -> Environment Variables):

| Variable | Value |
|---|---|
| SECRET_KEY | long random string (32+ chars) |
| DEMO_MODE | true (seeds demo tickets) |
| ALLOW_DEMO_ADMIN_HEADER | true (needed for the dashboard in demo mode) |
| DATABASE_URL | Postgres URL for persistent data; leave unset for demo-only SQLite in /tmp |
| GEMINI_API_KEY | optional |

Do NOT set APP_ENV=production together with DEMO_MODE=true; the app refuses to start.
Leave VITE_API_URL unset: the production build calls /api on the same domain.
Check after deploy: https://<your-domain>/api/health
