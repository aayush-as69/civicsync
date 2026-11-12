# CivicSync — Team BitBenders

> **From civic complaint to coordinated resolution.**

CivicSync is a local-first civic maintenance prototype that converts natural-language complaints into structured, traceable service tickets. It combines a React/Vite interface, Flask API, database-backed routing and optional Gemini analysis.

## Problem

Citizens can describe maintenance problems naturally without knowing the responsible department. CivicSync turns that report into:

**Complaint → Analysis → Category → Department → Ticket → Status history → Workflow**

## Implemented capabilities

| Capability | Status |
|---|---|
| Complaint submission | ✅ |
| Structured analysis | ✅ |
| Gemini analysis | ✅ Optional |
| Deterministic fallback | ✅ |
| Department routing | ✅ |
| Ticket history | ✅ |
| Idempotent ticket creation | ✅ |
| Citizen tracking token | ✅ |
| Demo admin dashboard | ✅ Controlled demo |
| Workflow events | ✅ |
| Fetch.ai/uAgents transport | ⚠️ Separate runtime |
| Production authentication | ❌ Not included |

## Architecture

~~~text
React + Vite
      │
      ▼
Flask REST API
      │
      ├── Analysis → Gemini or deterministic fallback
      ├── Routing  → department rules
      └── SQLAlchemy → SQLite / MySQL
                           │
                           ▼
                    Ticket + History
~~~

Flask remains authoritative for validation and persistence. AI analysis produces a constrained proposal and does not directly write database records.

## Project structure

~~~text
frontend/    React + TypeScript + Vite
backend/     Flask API, agents, models and tests
api/         Vercel serverless entry point
docs/        Technical documentation
~~~

## Quick start

### Backend

~~~powershell
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python backend\app.py
~~~

### Frontend

~~~powershell
cd frontend
npm ci
npm run dev
~~~

Open the Vite URL, normally http://localhost:5173. The Flask API normally runs at http://127.0.0.1:5000.

## Configuration

| Variable | Purpose |
|---|---|
| DATABASE_URL | SQLAlchemy database URL |
| SECRET_KEY | Application signing secret |
| FRONTEND_URL | Allowed browser origin(s) |
| GEMINI_API_KEY | Enables live Gemini analysis |
| DEMO_MODE | Enables controlled sample records |
| ALLOW_DEMO_ADMIN_HEADER | Local/demo-only admin shortcut |
| ADMIN_API_TOKEN | Optional server-side bearer token |
| UAGENTS_ENABLED / AGENTVERSE_URL | Optional distributed-agent configuration |

Never put secrets or agent seeds in frontend code.

## Demo flow

1. Open Report a Complaint.
2. Enter a maintenance complaint and location.
3. Preview the structured analysis.
4. Create the ticket.
5. Use the tracking token to retrieve the protected ticket.
6. Open Department Dashboard to advance the demo workflow.
7. Inspect AI Agents for actual stored workflow events and configuration status.

## API

| Endpoint | Access | Purpose |
|---|---|---|
| GET /api/health | Public | Health/configuration status |
| POST /api/complaints/analyze | Public | Unsaved structured analysis |
| POST /api/complaints | Public | Validate, route and persist ticket |
| GET /api/tickets/<reference> | Tracking token | Protected citizen lookup |
| GET /api/tickets | Demo admin | Queue/list tickets |
| PATCH /api/tickets/<reference>/status | Demo admin | Status transition and history |
| GET /api/departments | Public | Department mappings |
| GET /api/dashboard/summary | Demo admin | Dashboard metrics |
| GET /api/agents/status | Public | Integration/configuration status |
| GET /api/agents/events | Demo admin | Persisted workflow events |

## Security boundary

The X-Demo-Role: admin mechanism is **not authentication**. It exists only for a controlled local/hackathon demonstration.

Production requires real administrator authentication, secure secrets, rate limiting, precise CORS, a production database with migrations and server-side credential handling.

Optional uAgents/Agentverse processes must be independently started and health-verified before the UI or documentation claims distributed agent execution.

## Testing

~~~powershell
cd backend
python -m pytest -q

cd ..\frontend
npm ci
npm run build
~~~

## Deployment

The repository includes a Vercel deployment path using the frontend as the static surface and Flask through api/index.py. Use persistent database storage for production rather than ephemeral SQLite.

See docs/DEPLOYMENT.md and docs/INTEGRATIONS.md for deployment and optional agent configuration.

## Documentation

Start with docs/README.md.

- docs/ARCHITECTURE.md — system and data flow
- docs/SETUP.md — local configuration
- docs/AI.md — Gemini and fallback behavior
- docs/API.md — endpoint details
- docs/SECURITY.md — security boundary
- docs/TESTING.md — verification
- docs/DEPLOYMENT.md — deployment
- docs/INTEGRATIONS.md — uAgents/Agentverse boundary

## Team BitBenders

- Aayush Singh — Team Leader / Backend & Agent Architecture
- Ayush Yadav — UI/UX Designer
- Kaushal Jha — Frontend Developer

## Project status

**Hackathon prototype.** The local workflow is functional, while production authentication, migration management, rate limiting and distributed-agent verification remain deployment requirements.

## License

See LICENSE.