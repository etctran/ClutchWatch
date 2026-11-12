# Progress

## M0: Setup and smoke test (2026-11-12)
- Project `clutchwatch-bywa6u` (us-central1), billing linked.
- Budget `clutchwatch-25usd`: $25, scoped to this project, alerts at 20/50/90/100% (confirmed via `gcloud billing budgets list`).
- APIs enabled: Run, Pub/Sub, BigQuery, Artifact Registry, Memorystore (Redis), Cloud Build, Secret Manager.
- Smoke service (`smoke/`, Python 3.12 Dockerfile) deployed to Cloud Run, then deleted.
- **Result:** plain fetch of `cdn.nba.com/.../todaysScoreboard_00.json` returns **HTTP 403** from Cloud Run, and also 403 from a residential laptop with curl.
  The block is on request headers (non-browser client), not on cloud IPs, so the spec's "run the poller locally" fallback does not help.
- Live-mode data access: **open decision** (see DECISIONS.md). Replay mode (historical data) is unaffected.
