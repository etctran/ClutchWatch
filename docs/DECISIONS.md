# Design decisions

## Container images use a Dockerfile, not buildpacks
Spec pins Python 3.12. Google's current Cloud Run buildpack builder only resolves Python 3.13+, so `--source` deploys with `.python-version=3.12` fail. A 3-line `python:3.12-slim` Dockerfile pins the runtime exactly and is what the real services need anyway.

## Live NBA CDN returns 403 to non-browser clients
M0 smoke test: `urllib` from Cloud Run and `curl` from a laptop both get 403 from `cdn.nba.com` live JSON. So the block is header-based, not IP-based. Libraries like `nba_api.live` get through by sending browser-like headers. Whether to do that is a deliberate choice (open). Without it, live mode is dropped and everything is demonstrated with the replayer, which feeds the identical downstream pipeline.
