# CivicSync — Team BitBenders

**From Civic Complaint to Coordinated Resolution.** CivicSync is a local-first hackathon prototype for converting natural-language civic maintenance reports into persistent, traceable service tickets.

## What works

- React + TypeScript + Vite frontend with seven functional routes.
- Flask REST API with SQLite local fallback and SQLAlchemy ORM models compatible with MySQL configuration.
- Structured Gemini REST API analysis when configured, with validated JSON output and explicit `local-fallback` behavior if Gemini is absent or unavailable.
- Three logical agent roles: User Interface Agent, Analysis Agent, and Routing Agent.
- Database-backed department rules, idempotency keys, ticket status history, audit-style workflow events, and controlled demo seed data.
- Token-protected citizen ticket retrieval. Administrative endpoints require the clearly marked local demo admin header; replace this mechanism with real authentication for production.

## Quick start

Use two terminals from the project root.

```powershell
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python backend\app.py
```

Then:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite address (normally `http://localhost:5173`). The API runs at `http://127.0.0.1:5000`.

## Demo flow

1. Open **Report a Complaint** and enter a report such as: `The streetlight outside the college gate has been broken for three days.` Location: `College main gate`.
2. Select **Preview analysis** to inspect the structured local analysis result.
3. Create the ticket. The confirmation includes a real reference and tracking token in the tracking link.
4. Follow the tracking link to view the protected ticket and its persisted timeline.
5. Use **Department Dashboard** to advance statuses in the clearly labelled local demo-admin workspace.
6. View **AI Agents** for actual stored local workflow events and runtime configuration—not fabricated remote connections.

Controlled sample records seed only once and carry a `Demo` label.

## Configuration

Copy `.env.example`; never commit `.env`.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Defaults to `sqlite:///civicsync.db`. Set a supported SQLAlchemy MySQL URL for production. |
| `SECRET_KEY` | Required secure secret outside local development. |
| `FRONTEND_URL` | Comma-separated permitted browser origins for CORS. |
| `GEMINI_API_KEY` | Enables a real Gemini analysis request. Blank or unavailable means local fallback. |
| `ALLOW_DEMO_ADMIN_HEADER` | Enables the insecure `X-Demo-Role: admin` header only for a controlled local demo. |
| `ADMIN_API_TOKEN` | Optional server-side bearer token for protected API requests; never bundle it into frontend code. |
| `UAGENTS_ENABLED` / `AGENTVERSE_URL` | Declare optional Fetch.ai/uAgents configuration. They do not by themselves prove remote agent messaging is running. |
| `DEMO_MODE` | Enables controlled seed records in local setup. |

## Architecture and Fetch.ai boundary

`Browser → Flask UI Agent → Analysis Agent → validated contract → Routing Agent → SQLAlchemy transaction → ticket/history/event records`

- **Flask** exposes the REST boundary and owns database transactions.
- **Analysis Agent** produces a constrained JSON contract. The deterministic fallback uses rules and reports `local-fallback` in each ticket.
- **Routing Agent** resolves a category through database `Department` mappings; unmatched reports route to **General Review Queue**.
- **uAgents/Agentverse** are not silently emulated. This prototype is fully usable with local function orchestration. A remote uAgents implementation should be run as a separate process with registered addresses, protocol schemas, and verified health checks before its UI state is presented as connected.

To prepare the optional actual uAgents transport, install `pip install -r backend/requirements-agent.txt`, set distinct `CIVICSYNC_ANALYSIS_AGENT_SEED` and `CIVICSYNC_ROUTING_AGENT_SEED` values in the deployment secret store, and run `python backend/uagents_runtime.py` once per role (`CIVICSYNC_AGENT_ROLE=analysis` or `routing`). The supplied runtime uses real `uagents` models and message handlers. The analysis process can forward to `CIVICSYNC_ROUTING_AGENT_ADDRESS`; the routing process can submit the complaint to `CIVICSYNC_FLASK_API_URL`, where Flask validates and persists it with an idempotency key. Configure both agent seeds and the routing agent address before testing this optional path. Flask remains authoritative for ticket persistence; this remote path is not automatically started by the main app.

## API summary

| Endpoint | Access | Description |
| --- | --- | --- |
| `GET /api/health` | public | Health and truthful integration configuration. |
| `POST /api/complaints/analyze` | public | Unsaved structured analysis. |
| `POST /api/complaints` | public | Validates, routes, and persists a ticket. Supports `Idempotency-Key`. |
| `GET /api/tickets/<reference>` | matching token | Private ticket lookup using `X-Tracking-Token`. |
| `GET /api/tickets` | demo admin | Filtered, paginated service queue. |
| `PATCH /api/tickets/<reference>/status` | demo admin | Legal status transition plus history record. |
| `GET /api/departments` | public | Configured department mappings. |
| `GET /api/dashboard/summary` | demo admin | Database-derived metrics. |
| `GET /api/agents/status` | public | Actual local/configuration status. |
| `GET /api/agents/events` | demo admin | Persisted workflow events. |

## Tests and production build

```powershell
cd backend
pytest -q

cd ..\frontend
npm run build
```

## Production notes

Before deployment: use MySQL with migrations, set a strong `SECRET_KEY`, set a precise production `FRONTEND_URL`, turn off demo mode, add rate limiting, and replace the demo `X-Demo-Role` mechanism with authenticated user and administrator roles. Gemini and Agentverse credentials belong in the deployment secret store—not in files or source control.

## Team BitBenders

- Aayush Singh — Team Leader
- Ayush Yadav Yadav — UI/UX Designer
- Kaushal Jha Jha — Frontend Developer


## Local setup and verification

1. Copy `.env.example` to `.env` in the project root. Keep `DEMO_MODE=true` and `ALLOW_DEMO_ADMIN_HEADER=true` only for a local presentation; do not expose this mode to the public internet.
2. Install backend dependencies: `python -m pip install -r backend/requirements.txt`.
3. Start the backend from `backend/`: `python app.py`.
4. Install frontend dependencies from `frontend/`: `npm ci`, then run `npm run dev`. For a deployed frontend, set `VITE_API_URL` to the deployed backend API base (for example, `https://your-api.example.com/api`) before building.
5. Run backend tests from `backend/`: `python -m pytest -q`.
6. Verify the frontend production build from `frontend/`: `npm run build`.

For production, set `APP_ENV=production`, `DEMO_MODE=false`, `ALLOW_DEMO_ADMIN_HEADER=false`, use a strong `SECRET_KEY`, configure a production database and migrations, add rate limiting, and implement a real administrator login/session flow before exposing administrator functions. The current frontend's `X-Demo-Role` header is strictly for a controlled local demo and is not production authentication. Do not bundle `ADMIN_API_TOKEN` into frontend JavaScript. Configure `GEMINI_API_KEY` to enable Gemini analysis; the app explicitly falls back to local keyword rules if the provider is unavailable.

See `PATCH_NOTES.md` for the fixes and remaining integration boundaries.


## Integration boundaries (read before presenting)

- **Local workflow is the default.** The normal complaint endpoint uses local Python orchestration; the AI Agents page describes that honestly.
- **Gemini is optional and unverified until tested live.** A configured key enables an HTTP request; provider failure falls back to local rules. Never commit `.env` or expose API keys.
- **Distributed uAgents are optional.** Start separate analysis and routing processes, configure their seeds/address and `CIVICSYNC_FLASK_API_URL`, then verify the returned `RoutingResult` and persisted ticket end to end before claiming remote multi-agent execution.
- **Admin UI is demo-only.** `X-Demo-Role` is not authentication. The backend supports a server-side bearer token for API access, but a full user login/session flow is not included in this prototype.
- **Database schema changes need migrations.** `db.create_all()` is for initial local setup; it does not upgrade existing production tables.
- **Verification must be run locally:** backend `python -m pytest -q`; frontend `npm ci` and `npm run build`. Static syntax checks alone do not prove runtime behavior.

## Deploying to Vercel

The repo deploys as a single Vercel project: `frontend/` is built with Vite and served statically, and Flask runs as a Python serverless function (`api/index.py`) behind `/api/*` (see `vercel.json`). Frontend and API share one domain, so no CORS setup or `VITE_API_URL` is needed.

**Via dashboard:** push the repo to GitHub → *Add New Project* → import it → leave Root Directory as the repo root (the framework preset is overridden by `vercel.json`) → set the environment variables below → Deploy.

**Via CLI:**

```bash
npm i -g vercel
vercel          # preview
vercel --prod   # production
```

**Environment variables (Project Settings → Environment Variables):**

| Variable | Value |
| --- | --- |
| `SECRET_KEY` | Random string, 32+ characters |
| `DATABASE_URL` | Postgres URL (Neon/Supabase/Vercel Postgres). Strongly recommended: without it the app uses SQLite in `/tmp`, which is wiped on cold starts. |
| `DEMO_MODE` | `true` for a hackathon demo (seeds sample data); `false` otherwise |
| `ALLOW_DEMO_ADMIN_HEADER` | `true` only for a public *demo* so the dashboard works; it is not real authentication |
| `ADMIN_API_TOKEN` | Optional server-side bearer token |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional Gemini analysis |

Do not set `APP_ENV=production` while the demo-admin header is on; the app refuses to start in that combination. The optional uAgents runtime is not deployed to Vercel (it needs long-running processes).
