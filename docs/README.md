# CivicSync Documentation

Technical documentation for CivicSync, the local-first civic complaint and routing prototype.

## Documentation map

| Document | Purpose |
|---|---|
| [Architecture](ARCHITECTURE.md) | Frontend, Flask API, analysis and routing flow |
| [Setup](SETUP.md) | Local development and environment configuration |
| [AI analysis](AI.md) | Gemini integration, validation and local fallback |
| [API](API.md) | Endpoint behavior and access boundaries |
| [Security](SECURITY.md) | Demo authentication boundary and production requirements |
| [Deployment](DEPLOYMENT.md) | Vercel and backend deployment model |
| [Testing](TESTING.md) | Backend tests and frontend build verification |
| [Integration boundaries](INTEGRATIONS.md) | uAgents/Agentverse and other optional integrations |

## Architecture

```text
React + Vite
     │
     ▼
 Flask REST API
     │
     ├── Analysis Agent
     │      ├── Gemini (optional)
     │      └── deterministic local fallback
     │
     ├── Routing Agent
     │      └── department rules
     │
     └── SQLAlchemy
            │
            ▼
        SQLite / MySQL
```

Flask remains authoritative for validation and persistence. AI analysis produces a constrained proposal; it does not directly mutate the database.

## Security boundary

The current demo-admin header is intentionally not production authentication. Production deployment requires real authenticated sessions or equivalent administrator identity controls, rate limiting, secure secrets and a production database configuration.

Optional uAgents/Agentverse processes must be independently started and health-verified before the UI or documentation claims distributed agent execution.