# CivicSync patch notes

## Changes in this revision

- Added real Gemini REST API analysis with a short timeout, structured JSON output validation, and explicit local fallback when the key is absent or the model fails.
- Health endpoint now checks database connectivity and reports degraded state when the database is unavailable; it does not claim Gemini is active merely because a key exists.
- Disabled demo mode by default. Demo-header administrator access is accepted only when demo mode and the explicit local-demo configuration are enabled. A server-side `ADMIN_API_TOKEN` bearer token is also supported for protected APIs.
- Production startup rejects a weak/default `SECRET_KEY` and rejects `DEMO_MODE=true`.
- Public ticket lookups no longer expose staff-only internal notes. Admin responses retain those fields.
- Idempotency replays no longer repeat the ticket tracking token. The original successful creation response still returns it once.
- Pagination errors return structured HTTP 400 responses.
- Resolving a ticket now requires a resolution summary.
- Dashboard status actions respect terminal statuses; the UI prompts for a resolution summary before resolving.
- Agent event fetch failures are displayed instead of being silently treated as an empty event list.
- Added regression tests for private notes, pagination, resolution summaries, token replay, and demo-header security.
- Removed local virtual environments, npm caches, generated databases, build output, and Python caches from the source archive.

## Important boundaries

- Gemini is attempted only when `GEMINI_API_KEY` is configured; if the request fails or the response is invalid, the workflow falls back to local keyword rules and labels the result `local-fallback`.
- The default complaint workflow remains local Python orchestration. The optional uAgents runtime now performs category/urgency analysis, can forward results to a configured routing-agent address, and can ask Flask to validate and persist a ticket. It remains optional and must be configured and tested with separate agent processes before presenting it as live.
- `ADMIN_API_TOKEN` is a server-side API token mechanism, not a complete user login/session system. Do not put it in a public frontend bundle. The `X-Demo-Role` header is for a controlled local demo only.
- Runtime tests and frontend build could not be completed in this environment because Python packages were unavailable and npm dependencies could not be installed offline. Run the verification steps in the README on a network-enabled machine.


## Follow-up hardening pass

- Gemini API keys are sent in the `x-goog-api-key` header instead of being embedded in the request URL.
- Gemini analysis preview derives its suggested department from the same canonical category mapping used by ticket routing.
- Public citizen ticket history no longer exposes free-form status notes; administrative responses retain staff-only details.
- Concurrent requests that race on the same idempotency key return the existing ticket without repeating the tracking token.
- Production startup now also rejects `ALLOW_DEMO_ADMIN_HEADER=true`; `APP_ENV=production` is supported as the explicit deployment environment setting.
- Health status says Gemini is configured but unverified rather than implying that the provider is working.
- The optional uAgents runtime validates correlation IDs, returns a `RoutingResult` to the original requester, and uses a worker thread for its synchronous HTTP request.
- The frontend reuses an idempotency key for retries of an unchanged report and rotates it when fields change or a new report begins.
- Analytics displays a visible error when its protected summary endpoint cannot be loaded.
- Added regression tests for public status-note privacy, Gemini API-key header handling, and canonical department mapping.

## Remaining release gates

This patch does not make the prototype production-ready by assertion. Run the backend test suite and frontend production build on a machine with dependencies available. The production administrator login/session flow, database migrations, and scalable rate limiting still need to be implemented before exposing the service publicly. Distributed uAgents and Gemini must be verified against live configured services before they are described as operational.
